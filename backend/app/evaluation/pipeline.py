"""自动化评测流水线：加载 → 并行执行 → 并行评分 → 归因分析 → 报告生成。

- 并发：执行/评分分别用 Semaphore 限流
- 断点续跑：CaseResult.stage 记录进度（pending→executed→judged），重跑自动跳过已完成阶段
- 追踪：每次 Agent 执行与 Judge 调用都记录 trace（Langfuse 或本地降级）
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.base import build_agent
from app.attribution.engine import analyze_case, summarize_findings
from app.core.config import settings
from app.core.db import SessionLocal
from app.evaluation import metrics
from app.evaluation.judge import Judge
from app.evaluation.report import generate_reports
from app.integrations.tracing import flush_langfuse, record_trace
from app.models import (
    Agent, AgentVersion, AttributionFinding, CaseResult, DatasetVersion,
    Dimension, DimensionScore, EvalCase, EvalRun, Report,
)

logger = logging.getLogger("agent-bench.pipeline")

# 进程内运行中的任务（取消用）
_running_tasks: dict[int, asyncio.Task] = {}


def _now():
    return datetime.now(timezone.utc)


def _j(text: str, default):
    try:
        return json.loads(text) if text else default
    except json.JSONDecodeError:
        return default


async def start_run(run_id: int) -> None:
    """由 BackgroundTasks 调度；必须是 async，才能拿到事件循环创建任务。"""
    task = asyncio.get_running_loop().create_task(_run_safe(run_id))
    _running_tasks[run_id] = task


def cancel_run(run_id: int) -> bool:
    task = _running_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


async def _run_safe(run_id: int) -> None:
    try:
        await execute_run(run_id)
    except asyncio.CancelledError:
        with SessionLocal() as db:
            run = db.get(EvalRun, run_id)
            if run and run.status not in ("done",):
                run.status, run.error = "cancelled", "用户取消"
                db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("run %s failed", run_id)
        with SessionLocal() as db:
            run = db.get(EvalRun, run_id)
            if run:
                run.status, run.error, run.finished_at = "failed", str(e)[:2000], _now()
                db.commit()
    finally:
        _running_tasks.pop(run_id, None)


async def execute_run(run_id: int) -> None:
    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        if run.status == "done":
            return
        run.status, run.started_at = "loading", run.started_at or _now()
        db.commit()

        dsv = db.get(DatasetVersion, run.dataset_version_id)
        cases: list[EvalCase] = sorted(dsv.cases, key=lambda c: c.seq)
        dim_codes = _j(run.dimension_codes, [])
        dims_all = db.execute(
            select(Dimension).where(Dimension.enabled.is_(True))
        ).scalars().all()
        dims = [d for d in dims_all if not dim_codes or d.code in dim_codes]
        if not dims:
            raise RuntimeError("没有可用的评测维度")

        av_ids = _j(run.agent_version_ids, [])
        avs: list[AgentVersion] = [db.get(AgentVersion, i) for i in av_ids]
        agents: dict[int, object] = {}
        for av in avs:
            agent = db.get(Agent, av.agent_id)
            av_note = json.loads(av.config or "{}")
            agents[av.id] = build_agent(agent.type, av_note)

        run.total_cases = len(cases) * len(avs)
        run.progress = 0
        db.commit()

        # ---------------- 阶段 1：并行执行 ----------------
        run.status = "executing"
        db.commit()
        sem = asyncio.Semaphore(run.concurrency)

        async def exec_one(case: EvalCase, av: AgentVersion):
            existing = db.execute(
                select(CaseResult).where(
                    CaseResult.run_id == run.id, CaseResult.case_id == case.id,
                    CaseResult.agent_version_id == av.id,
                )
            ).scalar_one_or_none()
            if existing and existing.stage in ("executed", "judged"):
                await _bump_progress(db, run)
                return
            result = existing or CaseResult(
                run_id=run.id, case_id=case.id, agent_version_id=av.id, seq=case.seq
            )
            async with sem:
                try:
                    out = await asyncio.wait_for(
                        agents[av.id].run(case.input, {"seq": case.seq}),
                        timeout=settings.AGENT_TIMEOUT_SECONDS + 30,
                    )
                except Exception as e:  # noqa: BLE001
                    from app.agents.base import AgentOutput

                    out = AgentOutput(error=f"{type(e).__name__}: {e}")
            trace_id = record_trace(
                run.id, f"exec_{av.id}_{case.seq}",
                name=f"agent-exec #{case.seq}",
                input_data=case.input,
                output_data={"output": out.output[:4000], "error": out.error,
                             "intermediate": out.intermediate},
                metadata={"agent_version_id": av.id, "case_seq": case.seq},
                latency_ms=out.latency_ms,
                tags=["agent-exec", run.name],
            )
            result.status = "error" if (out.error or not out.output.strip()) else "ok"
            result.output, result.error = out.output, out.error
            result.intermediate = json.dumps(out.intermediate, ensure_ascii=False)
            result.latency_ms = out.latency_ms
            result.token_usage = json.dumps(out.token_usage, ensure_ascii=False)
            result.trace_id = trace_id
            result.stage = "executed"
            if not existing:
                db.add(result)
            await _bump_progress(db, run)

        await asyncio.gather(*[exec_one(c, av) for c in cases for av in avs])
        for a in agents.values():
            await a.aclose()

        # ---------------- 阶段 2：并行评分 ----------------
        run.status = "scoring"
        db.commit()
        judge = Judge(
            [{"code": d.code, "name": d.name, "rubric": d.rubric, "weight": d.weight} for d in dims],
            mode=run.judge_mode,
        )
        judge_sem = asyncio.Semaphore(run.concurrency)
        results: list[CaseResult] = db.execute(
            select(CaseResult).where(CaseResult.run_id == run.id)
        ).scalars().all()
        case_map = {c.id: c for c in cases}

        async def score_one(res: CaseResult):
            if res.stage == "judged" or res.status != "ok":
                return
            case = case_map[res.case_id]
            case_flat = {
                "input": case.input,
                "expected_output": case.expected_output,
                "reference_context": case.reference_context,
                "intermediate": _j(res.intermediate, []),
            }
            async with judge_sem:
                scores = await judge.judge_case(
                    case=case_flat, output=res.output, run_id=run.id,
                    case_key=f"{res.agent_version_id}_{res.seq}",
                )
            for s in res.scores:  # 重跑覆盖旧评分
                db.delete(s)
            db.flush()
            for s in scores:
                db.add(DimensionScore(
                    case_result_id=res.id, dimension_code=s["code"],
                    score=s["score"], rationale=s["rationale"],
                    evidence=s["evidence"], error=s["error"],
                ))
            res.stage = "judged"
            db.commit()

        await asyncio.gather(*[score_one(r) for r in results])
        db.expire_all()
        results = db.execute(
            select(CaseResult).where(CaseResult.run_id == run.id)
        ).scalars().all()

        # ---------------- 阶段 3：归因分析 ----------------
        run.status = "attributing"
        db.commit()
        for res in results:
            case = case_map[res.case_id]
            score_map = {s.dimension_code: s.score for s in res.scores}
            needs = res.status != "ok" or any(
                v < settings.PASS_THRESHOLD for v in score_map.values()
            )
            if not needs:
                continue
            # 重跑覆盖旧归因，避免重复
            for old in db.execute(
                select(AttributionFinding).where(AttributionFinding.case_result_id == res.id)
            ).scalars():
                db.delete(old)
            case_flat = {
                "input": case.input,
                "expected_output": case.expected_output,
                "reference_context": case.reference_context,
                "tools_spec": _j(case.tools_spec, {}),
            }
            res_flat = {
                "output": res.output, "error": res.error,
                "intermediate": _j(res.intermediate, []), "scores": score_map,
            }
            for f in analyze_case(case_flat, res_flat):
                db.add(AttributionFinding(case_result_id=res.id, **f))
        db.commit()

        # ---------------- 阶段 4：报告 ----------------
        run.status = "reporting"
        db.commit()
        generate_reports(db, run.id)
        run = db.get(EvalRun, run_id)
        run.status, run.finished_at = "done", _now()
        db.commit()
        flush_langfuse()
    finally:
        db.close()


async def _bump_progress(db, run) -> None:
    run.progress += 1
    db.commit()
