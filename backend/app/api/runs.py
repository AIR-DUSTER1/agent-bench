"""评测任务路由：创建（single/ab）、进度查询、重试、取消、报告、归因。"""
from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.evaluation.pipeline import cancel_run, start_run
from app.models import Agent, AgentVersion, DatasetVersion, EvalRun, Report
from app.schemas import RunCreate

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
    return {
        "id": r.id, "name": r.name, "mode": r.mode, "status": r.status,
        "sides": sides, "dataset_version_id": r.dataset_version_id,
        "judge_model": r.judge_model, "judge_mode": r.judge_mode,
        "dimension_codes": json.loads(r.dimension_codes or "[]"),
        "concurrency": r.concurrency, "progress": r.progress, "total_cases": r.total_cases,
        "error": r.error,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "created_at": r.created_at.isoformat(),
    }


@router.post("", status_code=201)
def create_run(body: RunCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    if len(body.agent_version_ids) == 2:
        mode = "ab"
    elif len(body.agent_version_ids) == 1:
        mode = "single"
    else:
        raise HTTPException(400, "agent_version_ids 需要 1 个（single）或 2 个（ab）")
    dsv = db.get(DatasetVersion, body.dataset_version_id)
    if not dsv or dsv.version == "draft":
        raise HTTPException(400, "dataset_version_id 必须是已发布版本（draft 不可评测）")
    run = EvalRun(
        name=body.name, mode=mode,
        agent_version_ids=json.dumps(body.agent_version_ids),
        dataset_version_id=body.dataset_version_id,
        judge_model=settings.judge_model, judge_mode=body.judge_mode,
        dimension_codes=json.dumps(body.dimension_codes),
        concurrency=body.concurrency,
    )
    db.add(run)
    db.commit()
    background.add_task(start_run, run.id)
    return {"id": run.id, "mode": mode}


@router.get("")
def list_runs(status: str | None = None, db: Session = Depends(get_db)):
    q = select(EvalRun).order_by(EvalRun.id.desc())
    if status:
        q = q.where(EvalRun.status == status)
    return [_run_out(db, r) for r in db.execute(q).scalars()]


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    out = _run_out(db, r)
    if r.status == "done":
        rep = db.execute(select(Report).where(Report.run_id == run_id)).scalars().first()
        if rep:
            out["report_id"] = rep.id
    return out


@router.post("/{run_id}/retry")
def retry_run(run_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    if r.status in ("executing", "scoring", "attributing", "reporting", "loading"):
        raise HTTPException(409, "任务运行中，如需重启请先取消")
    r.status, r.error = "pending", ""
    db.commit()
    background.add_task(start_run, run_id)
    return {"ok": True}


@router.post("/{run_id}/cancel")
def cancel_run_api(run_id: int, db: Session = Depends(get_db)):
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    ok = cancel_run(run_id)
    if not ok:
        r.status, r.error = "cancelled", "进程内无运行任务，直接标记取消"
        db.commit()
    return {"cancelled": True}


@router.get("/{run_id}/report")
def get_report(run_id: int, db: Session = Depends(get_db)):
    rep = db.execute(select(Report).where(Report.run_id == run_id)).scalars().first()
    if not rep:
        raise HTTPException(404, "报告尚未生成（任务未完成）")
    return {
        "id": rep.id, "run_id": rep.run_id, "kind": rep.kind,
        "summary": json.loads(rep.summary or "{}"),
        "html_path": rep.html_path, "md_path": rep.md_path,
        "created_at": rep.created_at.isoformat(),
    }


@router.get("/{run_id}/report/html")
def get_report_html(run_id: int, db: Session = Depends(get_db)):
    rep = db.execute(select(Report).where(Report.run_id == run_id)).scalars().first()
    if not rep or not rep.html_path:
        raise HTTPException(404, "报告尚未生成")
    return FileResponse(rep.html_path, media_type="text/html")
