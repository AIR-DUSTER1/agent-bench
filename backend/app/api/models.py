"""模型供应商与模型注册表路由。

安全：api_key 只写不读——响应一律脱敏（前 6 位 + ***）；更新时空字符串表示不改 key。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import ModelEntry, ModelProvider
from app.models.registry import THINKING_LEVELS
from app.schemas import ModelEntryCreate, ModelEntryUpdate, ProviderCreate, ProviderUpdate

router = APIRouter(prefix="/api/models", tags=["models"])


def _check_thinking(level: str | None) -> None:
    if level is not None and level not in THINKING_LEVELS:
        raise HTTPException(400, f"thinking_level 必须是 {THINKING_LEVELS}")


def _mask(key: str) -> str:
    return (key[:6] + "***") if key and len(key) > 10 else ("***" if key else "")


def _provider_out(p: ModelProvider, with_key_hint: bool = True) -> dict:
    return {
        "id": p.id, "name": p.name, "base_url": p.base_url, "enabled": p.enabled,
        "api_key_masked": _mask(p.api_key) if with_key_hint else "",
        "created_at": p.created_at.isoformat(),
    }


def _entry_out(db: Session, e: ModelEntry) -> dict:
    p = db.get(ModelProvider, e.provider_id)
    return {
        "id": e.id, "provider_id": e.provider_id,
        "provider_name": p.name if p else "?",
        "name": e.name, "display_name": e.display_name, "enabled": e.enabled,
        "thinking_level": e.thinking_level or "high",
        "label": f"{p.name if p else '?'}/{e.name}",
        "created_at": e.created_at.isoformat(),
    }


@router.get("/providers")
def list_providers(db: Session = Depends(get_db)) -> list[dict]:
    return [_provider_out(p) for p in db.execute(select(ModelProvider).order_by(ModelProvider.id)).scalars()]


@router.post("/providers", status_code=201)
def create_provider(body: ProviderCreate, db: Session = Depends(get_db)) -> dict:
    if db.query(ModelProvider).filter_by(name=body.name).first():
        raise HTTPException(409, f"供应商已存在: {body.name}")
    p = ModelProvider(name=body.name, base_url=body.base_url, api_key=body.api_key, enabled=body.enabled)
    db.add(p)
    db.commit()
    return _provider_out(p)


@router.put("/providers/{provider_id}")
def update_provider(provider_id: int, body: ProviderUpdate, db: Session = Depends(get_db)) -> dict:
    p = db.get(ModelProvider, provider_id)
    if not p:
        raise HTTPException(404, "供应商不存在")
    for field, val in body.model_dump(exclude_none=True).items():
        # api_key 传空串 = 不修改（前端不回显明文，只有用户主动填新 key 才覆盖）
        if field == "api_key" and val == "":
            continue
        setattr(p, field, val)
    db.commit()
    return _provider_out(p)


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db)) -> dict:
    p = db.get(ModelProvider, provider_id)
    if not p:
        raise HTTPException(404, "供应商不存在")
    db.delete(p)  # 模型级联删除；引用它的 run/agent 配置会在启动时报「不存在或已停用」
    db.commit()
    return {"ok": True}


@router.get("")
def list_models(db: Session = Depends(get_db)) -> list[dict]:
    return [_entry_out(db, e) for e in db.execute(select(ModelEntry).order_by(ModelEntry.id)).scalars()]


@router.post("", status_code=201)
def create_model(body: ModelEntryCreate, db: Session = Depends(get_db)) -> dict:
    _check_thinking(body.thinking_level)
    if not db.get(ModelProvider, body.provider_id):
        raise HTTPException(404, "供应商不存在")
    dup = db.query(ModelEntry).filter_by(provider_id=body.provider_id, name=body.name).first()
    if dup:
        raise HTTPException(409, f"该供应商下模型已存在: {body.name}")
    e = ModelEntry(provider_id=body.provider_id, name=body.name,
                   display_name=body.display_name or body.name, enabled=body.enabled,
                   thinking_level=body.thinking_level)
    db.add(e)
    db.commit()
    return _entry_out(db, e)


@router.put("/{model_id}")
def update_model(model_id: int, body: ModelEntryUpdate, db: Session = Depends(get_db)) -> dict:
    _check_thinking(body.thinking_level)
    e = db.get(ModelEntry, model_id)
    if not e:
        raise HTTPException(404, "模型不存在")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(e, field, val)
    db.commit()
    return _entry_out(db, e)


@router.delete("/{model_id}")
def delete_model(model_id: int, db: Session = Depends(get_db)) -> dict:
    e = db.get(ModelEntry, model_id)
    if not e:
        raise HTTPException(404, "模型不存在")
    db.delete(e)
    db.commit()
    return {"ok": True}
