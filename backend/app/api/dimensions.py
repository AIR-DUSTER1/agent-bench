"""评测维度路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Dimension
from app.schemas import DimensionCreate, DimensionUpdate

router = APIRouter(prefix="/api/dimensions", tags=["dimensions"])


@router.get("")
def list_dimensions(db: Session = Depends(get_db)) -> list[dict]:
    dims = db.execute(select(Dimension).order_by(Dimension.weight.desc())).scalars().all()
    return [
        {"code": d.code, "name": d.name, "description": d.description, "rubric": d.rubric,
         "weight": d.weight, "is_builtin": d.is_builtin,
         "applicable_types": d.applicable_types, "enabled": d.enabled}
        for d in dims
    ]


@router.post("", status_code=201)
def create_dimension(body: DimensionCreate, db: Session = Depends(get_db)) -> dict:
    if db.get(Dimension, body.code):
        raise HTTPException(409, f"维度 code 已存在: {body.code}")
    d = Dimension(**body.model_dump(), is_builtin=False)
    db.add(d)
    db.commit()
    return {"code": d.code}


@router.put("/{code}")
def update_dimension(code: str, body: DimensionUpdate, db: Session = Depends(get_db)) -> dict:
    d = db.get(Dimension, code)
    if not d:
        raise HTTPException(404, "维度不存在")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(d, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/{code}")
def delete_dimension(code: str, db: Session = Depends(get_db)) -> dict:
    d = db.get(Dimension, code)
    if not d:
        raise HTTPException(404, "维度不存在")
    if d.is_builtin:
        raise HTTPException(400, "内置维度不可删除，可停用（enabled=false）")
    db.delete(d)
    db.commit()
    return {"ok": True}
