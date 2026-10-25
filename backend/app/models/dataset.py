"""评测集、版本快照与样本。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow


class Dataset(TimestampMixin, Base):
    __tablename__ = "dataset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # 适用 Agent 类型：逗号分隔（用于导入时场景化必填校验）
    target_types: Mapped[str] = mapped_column(String(128), default="prompt,rag,tool")

    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset", order_by="DatasetVersion.id"
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(32))  # v1, v2, ...
    note: Mapped[str] = mapped_column(Text, default="")
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_summary: Mapped[str] = mapped_column(Text, default="{}")  # 发布时质量快照 JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="versions")
    cases: Mapped[list["EvalCase"]] = relationship(
        back_populates="dataset_version", order_by="EvalCase.seq", cascade="all, delete-orphan"
    )


class EvalCase(Base):
    __tablename__ = "eval_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer, default=0)  # 版本内序号
    input: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str] = mapped_column(Text, default="")
    reference_context: Mapped[str] = mapped_column(Text, default="")  # RAG 幻觉比对参考
    tools_spec: Mapped[str] = mapped_column(Text, default="{}")       # {"expected_tool":..., "expected_args":...}
    difficulty: Mapped[str] = mapped_column(String(16), default="medium")  # easy|medium|hard
    tags: Mapped[str] = mapped_column(Text, default="{}")  # {"domain":...,"scenario":...,"risk":...}
    meta: Mapped[str] = mapped_column(Text, default="{}")

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="cases")
