"""Agent 注册与版本（版本为不可变快照，评测绑定版本保证可复现）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow

# prompt | rag | tool | external_http | external_cli
AGENT_TYPES = ("prompt", "rag", "tool", "external_http", "external_cli")


class Agent(TimestampMixin, Base):
    __tablename__ = "agent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(32))  # AGENT_TYPES

    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="agent", order_by="AgentVersion.id"
    )


class AgentVersion(Base):
    __tablename__ = "agent_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(32))  # v1, v2, ...
    config: Mapped[str] = mapped_column(Text)  # JSON：模型/系统提示/工具/检索参数/外部端点等
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent: Mapped[Agent] = relationship(back_populates="versions")
