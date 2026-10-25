"""自动化评测流水线：加载 → 并行执行 → 并行评分 → 归因分析 → 报告生成。

- 并发：执行用 run.concurrency、评分用 settings.JUDGE_CONCURRENCY，分别 Semaphore 限流
- 断点续跑：CaseResult.stage 记录进度（pending→executed→judged），重跑跳过已完成阶段，
  重入同一阶段前先删旧产物（评分/归因），保证幂等（AGENTS.md §2.4）
- 失败隔离：单样本异常落库不中断整批；Trace 上报失败不影响主流程
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agents.base import AgentOutput, build_agent
from app.attribution.engine import analyze_case
from app.core.config import settings
from app.core.db import SessionLocal
from app.evaluation.judge import Judge
from app.evaluation.report import generate_reports
from app.integrations.tracing import flush_langfuse, record_trace
from app.models import (
    Agent, AgentVersion, AttributionFinding, CaseResult, DatasetVersion,
    Dimension, DimensionScore, EvalCase, EvalRun, RunStatus,
)

logger = logging.getLogger("agent-bench.pipeline")

# 进程内运行中的任务（取消用）
_running_tasks: dict[int, asyncio.Task] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _j(text: str | None, default: Any) -> Any:
    try:
        return json.loads(text) if text else default
    except json.JSONDecodeError:
        return default


async def start_run(run_id: int) -> None:
    """由 BackgroundTasks 调度。必须是 async：同步 def 会被 starlette 丢进线程池，
    拿不到事件循环（历史上两次踩坑，禁止改回 def）。"""
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
            if run and run.status != "done":
                run.status, run.error = RunStatus.CANCELLED, "用户取消"
                db.commit()
    except Exception as e:  # noqa: BLE001 顶层兜底：失败原因必须落库可见
        logger.exception("run %s failed", run_id)
        with SessionLocal() as db:
            run = db.get(EvalRun, run_id)
            if run:
                run.status, run.error, run.finished_at = RunStatus.FAILED, str(e)[:2000], _now()
                db.commit()
    finally:
        _running_tasks.pop(run_id, None)


# ---------------- 阶段上下文 ----------------

@dataclass
class RunContext:
    """一次流水线执行所需的全量只读上下文（阶段函数间传递，避免重复查询）。"""
    run: EvalRun
    cases: list[EvalCase]
    case_map: dict[int, EvalCase]
    dims: list[dict]  # [{code,name,rubric,weight}]
    avs: list[AgentVersion]
    agents: dict[int, Any] = field(default_factory=dict)


async def execute_run(run_id: int) -> None:
    """编排四个阶段；任何阶段抛错由 _run_safe 统一落库。"""
    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        if run.status == RunStatus.DONE:
            return
        run.status = RunStatus.LOADING
        run.started_at = run.started_at or _now()
        db.commit()

        ctx = _load_context(db, run)
        run.total_cases = len(ctx.cases) * len(ctx.avs)
        run.progress = 0
        db.commit()

        try:
            await _execute_phase(db, ctx)
            await _score_phase(db, ctx)
            _attribute_phase(db, ctx)
            _report_phase(db, ctx)
        finally:
            # 资源释放不依赖前序阶段成败（AGENTS.md §4.6）
            for agent in ctx.agents.values():
                await agent.aclose()

        run = db.get(EvalRun, run_id)
        run.status, run.finished_at = RunStatus.DONE, _now()
        db.commit()
        flush_langfuse()
    finally:
        db.close()


def _load_context(db, run: EvalRun) -> RunContext:
    dsv = db.get(DatasetVersion, run.dataset_version_id)
    cases: list[EvalCase] = sorted(dsv.cases, key=lambda c: c.seq)
    dim_codes = _j(run.dimension_codes, [])
    dims_all = db.execute(select(Dimension).where(Dimension.enabled.is_(True))).scalars().all()
    dims = [
        {"code": d.code, "name": d.name, "rubric": d.rubric, "weight": d.weight}
        for d in dims_all if not dim_codes or d.code in dim_codes
    ]
    if not dims:
        raise RuntimeError("没有可用的评测维度")
    avs = [db.get(AgentVersion, i) for i in _j(run.agent_version_ids, [])]
    if not avs or any(av is None for av in avs):
        raise RuntimeError("存在无效的 agent_version_id")
    agents = {}
    for av in avs:
        agent = db.get(Agent, av.agent_id)
        agents[av.id] = build_agent(agent.type, _j(av.config, {}))
    return RunContext(run=run, cases=cases, case_map={c.id: c for c in cases},
                      dims=dims, avs=avs, agents=agents)


# ---------------- 阶段 1：并行执行 ----------------

async def _execute_phase(db, ctx: RunContext) -> None:
    ctx.run.status = RunStatus.EXECUTING
    db.commit()
    sem = asyncio.Semaphore(ctx.run.concurrency)

    async def exec_one(case: EvalCase, av: AgentVersion) -> None:
        existing = db.execute(
            select(CaseResult).where(
                CaseResult.run_id == ctx.run.id, CaseResult.case_id == case.id,
                CaseResult.agent_version_id == av.id,
            )
        ).scalar_one_or_none()
        if existing and existing.stage in ("executed", "judged"):
            await _bump_progress(db, ctx.run)
            return
        result = existing or CaseResult(
            run_id=ctx.run.id, case_id=case.id, agent_version_id=av.id, seq=case.seq
        )
        async with sem:
            out = await _run_agent(ctx.agents[av.id], case)
        result.status = "error" if (out.error or not out.output.strip()) else "ok"
        result.output, result.error = out.output, out.error
        result.intermediate = json.dumps(out.intermediate, ensure_ascii=False)
        result.latency_ms = out.latency_ms
        result.token_usage = json.dumps(out.token_usage, ensure_ascii=False)
        result.trace_id = record_trace(
            ctx.run.id, f"exec_{av.id}_{case.seq}",
            name=f"agent-exec #{case.seq}",
            input_data=case.input,
            output_data={"output": out.output[:4000], "error": out.error,
                         "intermediate": out.intermediate},
            metadata={"agent_version_id": av.id, "case_seq": case.seq},
            latency_ms=out.latency_ms,
            tags=["agent-exec", ctx.run.name],
        )
        result.stage = "executed"
        if not existing:
            db.add(result)
        await _bump_progress(db, ctx.run)

    await asyncio.gather(*[exec_one(c, av) for c in ctx.cases for av in ctx.avs])


async def _run_agent(agent: Any, case: EvalCase) -> AgentOutput:
    """带总超时的单样本执行；异常归一化为 error 输出，不中断整批。"""
    try:
        return await asyncio.wait_for(
            agent.run(case.input, {"seq": case.seq}),
            timeout=settings.AGENT_TIMEOUT_SECONDS + 30,
        )
    except Exception as e:  # noqa: BLE001
        return AgentOutput(error=f"{type(e).__name__}: {e}")


async def _bump_progress(db, run: EvalRun) -> None:
    run.progress += 1
    db.commit()


# ---------------- 阶段 2：并行评分 ----------------

async def _score_phase(db, ctx: RunContext) -> None:
    ctx.run.status = RunStatus.SCORING
    db.commit()
    judge = Judge(ctx.dims, mode=ctx.run.judge_mode)
    judge_sem = asyncio.Semaphore(settings.JUDGE_CONCURRENCY)
    results = db.execute(
        select(CaseResult).where(CaseResult.run_id == ctx.run.id)
    ).scalars().all()

    async def score_one(res: CaseResult) -> None:
        if res.stage == "judged" or res.status != "ok":
            return
        case = ctx.case_map[res.case_id]
        case_flat = {
            "input": case.input,
            "expected_output": case.expected_output,
            "reference_context": case.reference_context,
            "intermediate": _j(res.intermediate, []),
        }
        async with judge_sem:
            scores, judge_usage = await judge.judge_case(
                case=case_flat, output=res.output, run_id=ctx.run.id,
                case_key=f"{res.agent_version_id}_{res.seq}",
            )
        for s in db.execute(  # 重跑覆盖旧评分（幂等，AGENTS.md §2.4）
            select(DimensionScore).where(DimensionScore.case_result_id == res.id)
        ).scalars():
            db.delete(s)
        db.flush()
        for s in scores:
            db.add(DimensionScore(
                case_result_id=res.id, dimension_code=s["code"],
                score=s["score"], rationale=s["rationale"],
                evidence=s["evidence"], error=s["error"],
            ))
        res.judge_usage = json.dumps(judge_usage, ensure_ascii=False)
        res.stage = "judged"
        db.commit()

    await asyncio.gather(*[score_one(r) for r in results])
    db.expire_all()


# ---------------- 阶段 3：归因分析 ----------------

def _attribute_phase(db, ctx: RunContext) -> None:
    ctx.run.status = RunStatus.ATTRIBUTING
    db.commit()
    results = db.execute(
        select(CaseResult).where(CaseResult.run_id == ctx.run.id)
    ).scalars().all()
    for res in results:
        score_map = {s.dimension_code: s.score for s in res.scores}
        needs = res.status != "ok" or any(
            v < settings.PASS_THRESHOLD for v in score_map.values()
        )
        if not needs:
            continue
        case = ctx.case_map[res.case_id]
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
        for old in db.execute(  # 重跑覆盖旧归因（幂等）
            select(AttributionFinding).where(AttributionFinding.case_result_id == res.id)
        ).scalars():
            db.delete(old)
        for f in analyze_case(case_flat, res_flat):
            db.add(AttributionFinding(case_result_id=res.id, **f))
    db.commit()


# ---------------- 阶段 4：报告 ----------------

def _report_phase(db, ctx: RunContext) -> None:
    ctx.run.status = RunStatus.REPORTING
    db.commit()
    generate_reports(db, ctx.run.id)
