"""数据治理路由：标签字典 + 质量报告查询。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.governance.tags import TAG_CATEGORIES
from app.models import QualityReport, TagDict
from app.schemas import TagCreate, TagUpdate

router = APIRouter(prefix="/api/governance", tags=["governance"])


@router.get("/tags")
def list_tags(db: Session = Depends(get_db)):
    tags = db.execute(select(TagDict).order_by(TagDict.category, TagDict.id)).scalars().all()
    out = {c: [] for c in TAG_CATEGORIES}
    for t in tags:
        out.setdefault(t.category, []).append(
            {"id": t.id, "value": t.value, "label": t.label, "enabled": t.enabled}
        )
    return out


@router.post("/tags", status_code=201)
def create_tag(body: TagCreate, db: Session = Depends(get_db)):
    if body.category not in TAG_CATEGORIES:
        raise HTTPException(400, f"category 必须是 {TAG_CATEGORIES}")
    if db.query(TagDict).filter_by(category=body.category, value=body.value).first():
        raise HTTPException(409, "标签已存在")
    t = TagDict(category=body.category, value=body.value, label=body.label or body.value)
    db.add(t)
    db.commit()
    return {"id": t.id}


@router.put("/tags/{tag_id}")
def update_tag(tag_id: int, body: TagUpdate, db: Session = Depends(get_db)):
    t = db.get(TagDict, tag_id)
    if not t:
        raise HTTPException(404, "标签不存在")
    if body.label is not None:
        t.label = body.label
    if body.enabled is not None:
        t.enabled = body.enabled
    db.commit()
    return {"ok": True}


@router.get("/quality-reports")
def quality_reports(dataset_id: int | None = None, db: Session = Depends(get_db)):
    q = select(QualityReport).order_by(QualityReport.id.desc()).limit(50)
    if dataset_id:
        q = q.where(QualityReport.dataset_id == dataset_id)
    return [
        {"id": r.id, "dataset_id": r.dataset_id, "triggered_by": r.triggered_by,
         "blockers": r.blockers, "warnings": r.warnings,
         "issues": json.loads(r.issues or "[]"), "created_at": r.created_at.isoformat()}
        for r in db.execute(q).scalars()
    ]
