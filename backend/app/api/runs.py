"""评测任务路由：创建（single/ab）、进度查询、重试、取消、报告、归因。"""
from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from statistics import mean

from app.core.config import settings
from app.core.db import get_db
from app.evaluation.metrics import normalize_usage, significance, sum_usage
from app.evaluation.pipeline import cancel_run, start_run
from app.models import (
    Agent, AgentVersion, CaseResult, DatasetVersion, Dimension, EvalCase, EvalRun,
    ModelEntry, ModelProvider, Report, RunStatus,
)
from app.schemas import ReplayIn, RunCreate

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run_out(db: Session, r: EvalRun) -> dict:
    av_ids = json.loads(r.agent_version_ids or "[]")
    sides = []
    for av_id in av_ids:
        av = db.get(AgentVersion, av_id)
        if av:
            a = db.get(Agent, av.agent_id)
            sides.append({"agent_version_id": av.id, "version": av.version,
                          "agent_name": a.name if a else "?", "agent_type": a.type if a else "?"})
    model_label = None
    if r.model_id:
        me = db.get(ModelEntry, r.model_id)
        if me:
            mp = db.get(ModelProvider, me.provider_id)
            model_label = f"{mp.name if mp else '?'}/{me.name}"
    return {
        "id": r.id, "name": r.name, "mode": r.mode, "status": r.status,
        "sides": sides, "dataset_version_id": r.dataset_version_id,
        "judge_model": r.judge_model, "judge_mode": r.judge_mode,
        "dimension_codes": json.loads(r.dimension_codes or "[]"),
        "concurrency": r.concurrency, "progress": r.progress, "total_cases": r.total_cases,
        "model_id": r.model_id, "model_label": model_label,
        "error": r.error,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "created_at": r.created_at.isoformat(),
    }


@router.post("", status_code=201)
def create_run(body: RunCreate, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    if len(body.agent_version_ids) == 2:
        mode = "ab"
    elif len(body.agent_version_ids) == 1:
        mode = "single"
    else:
        raise HTTPException(400, "agent_version_ids 需要 1 个（single）或 2 个（ab）")
    dsv = db.get(DatasetVersion, body.dataset_version_id)
    if not dsv or dsv.version == "draft":
        raise HTTPException(400, "dataset_version_id 必须是已发布版本（draft 不可评测）")
    if body.model_id is not None and not db.get(ModelEntry, body.model_id):
        raise HTTPException(400, f"model_id={body.model_id} 不存在")
    run = EvalRun(
        name=body.name, mode=mode,
        agent_version_ids=json.dumps(body.agent_version_ids),
        dataset_version_id=body.dataset_version_id,
        judge_model=settings.judge_model, judge_mode=body.judge_mode,
        dimension_codes=json.dumps(body.dimension_codes),
        concurrency=body.concurrency or settings.EXEC_CONCURRENCY,
        model_id=body.model_id,
    )
    db.add(run)
    db.commit()
    background.add_task(start_run, run.id)
    return {"id": run.id, "mode": mode}


@router.get("")
def list_runs(status: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    q = select(EvalRun).order_by(EvalRun.id.desc())
    if status:
        q = q.where(EvalRun.status == status)
    return [_run_out(db, r) for r in db.execute(q).scalars()]


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    out = _run_out(db, r)
    if r.status == "done":
        rep = db.execute(select(Report).where(Report.run_id == run_id)).scalars().first()
        if rep:
            out["report_id"] = rep.id
    results = db.execute(select(CaseResult).where(CaseResult.run_id == run_id)).scalars().all()
    out["token_summary"] = {
        "agent": sum_usage(json.loads(x.token_usage or "{}") for x in results),
        "judge": sum_usage(json.loads(x.judge_usage or "{}") for x in results),
    }
    return out


# 运行中状态集合（重试守卫）：任务处于这些状态时禁止重启
_ACTIVE_STATUSES = {
    RunStatus.LOADING, RunStatus.EXECUTING, RunStatus.SCORING,
    RunStatus.ATTRIBUTING, RunStatus.REPORTING,
}


@router.post("/{run_id}/retry")
def retry_run(run_id: int, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    if r.status in _ACTIVE_STATUSES:
        raise HTTPException(409, "任务运行中，如需重启请先取消")
    r.status, r.error = RunStatus.PENDING, ""
    db.commit()
    background.add_task(start_run, run_id)
    return {"ok": True}


@router.post("/{run_id}/cancel")
def cancel_run_api(run_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    ok = cancel_run(run_id)
    if not ok:
        r.status, r.error = RunStatus.CANCELLED, "进程内无运行任务，直接标记取消"
        db.commit()
    return {"cancelled": True}


@router.get("/{run_id}/report")
def get_report(run_id: int, db: Session = Depends(get_db)) -> dict:
    rep = _latest_report(db, run_id)
    if not rep:
        raise HTTPException(404, "报告尚未生成（任务未完成）")
    return {
        "id": rep.id, "run_id": rep.run_id, "kind": rep.kind,
        "summary": json.loads(rep.summary or "{}"),
        "html_path": rep.html_path, "md_path": rep.md_path,
        "created_at": rep.created_at.isoformat(),
    }


@router.get("/{run_id}/report/html")
def get_report_html(run_id: int, db: Session = Depends(get_db)) -> FileResponse:
    rep = _latest_report(db, run_id)
    if not rep or not rep.html_path:
        raise HTTPException(404, "报告尚未生成")
    return FileResponse(rep.html_path, media_type="text/html")


@router.get("/{run_id}/tokens")
def get_run_tokens(run_id: int, db: Session = Depends(get_db)) -> dict:
    """单次评测的 token 统计：逐样本明细（被测 + Judge 分列）与汇总。"""
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    results = db.execute(
        select(CaseResult).where(CaseResult.run_id == run_id).order_by(CaseResult.id)
    ).scalars().all()
    agent_map = {a.id: a for a in db.execute(select(Agent)).scalars()}
    av_map = {av.id: av for av in db.execute(select(AgentVersion)).scalars()}
    rows, agent_raw, judge_raw = [], [], []
    for res in results:
        av = av_map.get(res.agent_version_id)
        agent_u = normalize_usage(json.loads(res.token_usage or "{}"))
        judge_u = normalize_usage(json.loads(res.judge_usage or "{}"))
        agent_raw.append(json.loads(res.token_usage or "{}"))
        judge_raw.append(json.loads(res.judge_usage or "{}"))
        a = agent_map.get(av.agent_id) if av else None
        rows.append({
            "case_result_id": res.id, "seq": res.seq, "status": res.status,
            "agent_name": a.name if a else "?", "agent_version": av.version if av else "?",
            "usage": agent_u, "judge_usage": judge_u,
        })
    return {
        "run_id": run_id,
        "rows": rows,
        "agent_total": sum_usage(agent_raw),
        "judge_total": sum_usage(judge_raw),
    }


@router.post("/{run_id}/replay", status_code=201)
def replay_run(run_id: int, body: ReplayIn, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    """升级验证：以既有 run 为模板（同 Agent 版本/并发/Judge），换数据集版本一键复评。"""
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    dsv = db.get(DatasetVersion, body.dataset_version_id)
    if not dsv or dsv.version == "draft":
        raise HTTPException(400, "dataset_version_id 必须是已发布版本（draft 不可评测）")
    run = EvalRun(
        name=body.name or f"{r.name} · 复评",
        mode=r.mode,
        agent_version_ids=r.agent_version_ids,
        dataset_version_id=body.dataset_version_id,
        judge_model=settings.judge_model,
        judge_mode=r.judge_mode,
        dimension_codes=r.dimension_codes,
        concurrency=r.concurrency,
        model_id=r.model_id,
    )
    db.add(run)
    db.commit()
    background.add_task(start_run, run.id)
    return {"id": run.id, "mode": run.mode}


def _weighted_score(scores: list, weight_by: dict[str, float]) -> float | None:
    """单样本加权总分（score=-1 的维度视为缺失，不参与）。"""
    valid = [(s.score, weight_by.get(s.dimension_code, 1.0)) for s in scores if s.score >= 0]
    if not valid:
        return None
    return sum(v * w for v, w in valid) / sum(w for _, w in valid)


@router.get("/{run_id}/compare/{other_id}")
def compare_runs(run_id: int, other_id: int, db: Session = Depends(get_db)) -> dict:
    """双 run 逐样本对比（升级验证）：以 case.input 对齐，按被测侧分组输出得分变化与显著性。"""
    ra, rb = db.get(EvalRun, run_id), db.get(EvalRun, other_id)
    if not ra or not rb:
        raise HTTPException(404, "任务不存在")
    weight_by = {d.code: d.weight for d in db.execute(select(Dimension)).scalars()}

    def side_scores(run: EvalRun) -> dict[int, dict[str, float | None]]:
        out: dict[int, dict[str, float | None]] = {}
        rows = db.execute(
            select(CaseResult, EvalCase)
            .join(EvalCase, CaseResult.case_id == EvalCase.id)
            .where(CaseResult.run_id == run.id)
        ).all()
        for res, case in rows:
            out.setdefault(res.agent_version_id, {})[case.input] = _weighted_score(res.scores, weight_by)
        return out

    sa, sb = side_scores(ra), side_scores(rb)
    agent_map = {a.id: a for a in db.execute(select(Agent)).scalars()}

    sides = []
    for av_id in json.loads(ra.agent_version_ids or "[]"):
        av = db.get(AgentVersion, av_id)
        a = agent_map.get(av.agent_id) if av else None
        map_a, map_b = sa.get(av_id, {}), sb.get(av_id, {})
        common = sorted(set(map_a) & set(map_b))
        rows = [{
            "input": i,
            "a_score": map_a[i], "b_score": map_b[i],
            "delta": (map_b[i] - map_a[i]) if map_a[i] is not None and map_b[i] is not None else None,
        } for i in common]
        diffs = [r["delta"] for r in rows if r["delta"] is not None]
        a_vals = [map_a[i] for i in common if map_a[i] is not None]
        b_vals = [map_b[i] for i in common if map_b[i] is not None]
        sides.append({
            "agent_version_id": av_id,
            "agent_name": a.name if a else "?",
            "version": av.version if av else "?",
            "paired": len(common),
            "rows": rows,
            "summary": {
                "a_mean": round(mean(a_vals), 3) if a_vals else None,
                "b_mean": round(mean(b_vals), 3) if b_vals else None,
                "delta_mean": round(mean(diffs), 3) if diffs else None,
                "win": sum(1 for d in diffs if d > 0),
                "tie": sum(1 for d in diffs if d == 0),
                "loss": sum(1 for d in diffs if d < 0),
                "significance": significance(diffs) if diffs else None,
            },
        })

    return {
        "a": {"run_id": ra.id, "name": ra.name, "dataset_version_id": ra.dataset_version_id},
        "b": {"run_id": rb.id, "name": rb.name, "dataset_version_id": rb.dataset_version_id},
        # 模板一致性提示：被测 Agent 不同则对比结论只具参考性
        "warning": None if ra.agent_version_ids == rb.agent_version_ids else "两个 run 的被测 Agent 配置不同，对比仅供参考",
        "sides": sides,
    }


def _latest_report(db: Session, run_id: int) -> Report | None:
    """重跑会生成多份报告，永远返回最新一份。"""
    return db.execute(
        select(Report).where(Report.run_id == run_id).order_by(Report.id.desc())
    ).scalars().first()
