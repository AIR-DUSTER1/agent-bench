"""模型供应商与模型注册表。

Agent 版本配置里只存 model_id 引用（版本不可变，但供应商换 key/换域名不应重发版本），
运行时由 integrations.model_registry.resolve_llm_params 解析为 base_url/api_key/model。
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# 思考等级：映射为 OpenAI 兼容 reasoning_effort 参数；off = 不发送（模型默认行为）
THINKING_LEVELS = ("off", "low", "medium", "high")


class ModelProvider(TimestampMixin, Base):
    __tablename__ = "model_provider"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)  # 显示名，如 DeepSeek
    base_url: Mapped[str] = mapped_column(String(256))
    api_key: Mapped[str] = mapped_column(Text, default="")  # 仅存库（backend/data/ 已 gitignore），回显一律脱敏
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ModelEntry(TimestampMixin, Base):
    __tablename__ = "model_entry"
    __table_args__ = (UniqueConstraint("provider_id", "name", name="uq_provider_model"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("model_provider.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))  # 模型 ID，如 deepseek-flash
    display_name: Mapped[str] = mapped_column(String(128), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    thinking_level: Mapped[str] = mapped_column(String(16), default="high")  # 思考等级，默认最高
