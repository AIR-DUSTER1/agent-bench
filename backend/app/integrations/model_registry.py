"""模型注册表解析：把配置中的 model_id 引用解析为 base_url/api_key/model。

优先级：run 级覆盖 > config.model_id 引用 > config 原生 base_url/model > 全局 .env 缺省。
外置 Agent（external_http/external_cli）不经过 LLM 工厂，解析对它们无副作用。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.registry import ModelEntry, ModelProvider


def resolve_llm_params(db: Session, config: dict, override_model_id: int | None = None) -> dict:
    cfg = dict(config or {})
    mid = override_model_id or cfg.pop("model_id", None)
    if not mid:
        return cfg
    entry = db.get(ModelEntry, int(mid))
    # enabled=None（未显式设置）视为启用，只拦截显式停用
    if not entry or entry.enabled is False:
        raise ValueError(f"model_id={mid} 不存在或已停用")
    provider = db.get(ModelProvider, entry.provider_id)
    if not provider or provider.enabled is False:
        raise ValueError(f"模型 {entry.name} 的供应商已停用")
    cfg["base_url"] = provider.base_url
    cfg["api_key"] = provider.api_key
    cfg["model"] = entry.name
    return cfg
