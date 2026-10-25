"""评测域模型：维度、任务、执行结果、评分、归因、报告、质量报告。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow

# single | ab
RUN_MODES = ("single", "ab")


class RunStatus(str, Enum):
    """评测任务状态机（唯一权威定义，流水线/路由一律引用本枚举）。"""
    PENDING = "pending"
    LOADING = "loading"
    EXECUTING = "executing"
    SCORING = "scoring"
    ATTRIBUTING = "attributing"
    REPORTING = "reporting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 兼容引用：状态取值全集
RUN_STATUS = tuple(s.value for s in RunStatus)


class Dimension(TimestampMixin, Base):
    __tablename__ = "dimension"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    rubric: Mapped[str] = mapped_column(Text, default="")     # 详细评分标准（Judge 提示词的一部分）
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_builtin: Mapped[bool] = mapped_column(default=False)
    # 适用的 Agent 类型，逗号分隔；空 = 全部
    applicable_types: Mapped[str] = mapped_column(String(128), default="")
    enabled: Mapped[bool] = mapped_column(default=True)


class EvalRun(TimestampMixin, Base):
    __tablename__ = "eval_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(16), default="single")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # single: [agent_version_id]；ab: [A, B]
    agent_version_ids: Mapped[str] = mapped_column(Text)  # JSON 数组
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_version.id"))
    judge_model: Mapped[str] = mapped_column(String(128), default="")
    judge_mode: Mapped[str] = mapped_column(String(16), default="single_call")  # single_call|per_dimension
    dimension_codes: Mapped[str] = mapped_column(Text, default="[]")  # 本次启用的维度 JSON
    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    # 发起评测时的模型覆盖（指向 model_entry.id）；空 = 用 Agent 版本配置/.env 全局模型
    model_id: Mapped[int | None] = mapped_column(ForeignKey("model_entry.id"), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)   # 已完成样本数
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list["CaseResult"]] = relationship(back_populates="run")


class CaseResult(Base):
    __tablename__ = "case_result"
    __table_args__ = (UniqueConstraint("run_id", "case_id", "agent_version_id", name="uq_result"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_run.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("eval_case.id", ondelete="CASCADE"))
    agent_version_id: Mapped[int] = mapped_column(ForeignKey("agent_version.id"))
    seq: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|ok|error
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    # 中间轨迹 JSON：[{type: retrieval|tool_call, ...}]，归因分析的数据基础
    intermediate: Mapped[str] = mapped_column(Text, default="[]")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    token_usage: Mapped[str] = mapped_column(Text, default="{}")
    # Judge（阅卷 LLM）的 token 用量 JSON：{"input_tokens","output_tokens","total_tokens"}
    judge_usage: Mapped[str] = mapped_column(Text, default="{}")
    trace_id: Mapped[str] = mapped_column(String(128), default="")
    # 断点续跑用阶段标记：executed | judged
    stage: Mapped[str] = mapped_column(String(16), default="pending")

    run: Mapped[EvalRun] = relationship(back_populates="results")
    scores: Mapped[list["DimensionScore"]] = relationship(
        back_populates="case_result", cascade="all, delete-orphan"
    )
    findings: Mapped[list["AttributionFinding"]] = relationship(
        back_populates="case_result", cascade="all, delete-orphan"
    )


class DimensionScore(Base):
    __tablename__ = "dimension_score"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_result_id: Mapped[int] = mapped_column(
        ForeignKey("case_result.id", ondelete="CASCADE"), index=True
    )
    dimension_code: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)          # 0-5
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")  # Judge 解析失败等异常记录

    case_result: Mapped[CaseResult] = relationship(back_populates="scores")


class AttributionFinding(Base):
    __tablename__ = "attribution_finding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_result_id: Mapped[int] = mapped_column(
        ForeignKey("case_result.id", ondelete="CASCADE"), index=True
    )
    layer: Mapped[str] = mapped_column(String(16))       # prompt|rag|tool
    issue_code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16), default="medium")  # high|medium|low
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")

    case_result: Mapped[CaseResult] = relationship(back_populates="findings")


class Report(Base):
    __tablename__ = "report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_run.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="summary")  # summary|ab_compare
    summary: Mapped[str] = mapped_column(Text, default="{}")  # 指标聚合 JSON
    html_path: Mapped[str] = mapped_column(Text, default="")
    md_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityReport(Base):
    __tablename__ = "quality_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id", ondelete="CASCADE"), index=True)
    triggered_by: Mapped[str] = mapped_column(String(32), default="manual")  # manual|import|publish
    blockers: Mapped[int] = mapped_column(Integer, default=0)  # 阻断问题数
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    issues: Mapped[str] = mapped_column(Text, default="[]")    # [{level,rule,case_seq,detail}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
