"""Pydantic 请求/响应模型（全部路由共用）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- Agent ----------
class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    type: str  # prompt|rag|tool|external_http|external_cli
    config: dict = Field(default_factory=dict)
    note: str = ""


class AgentVersionCreate(BaseModel):
    config: dict
    note: str = ""


class AgentTestInput(BaseModel):
    input: str
    version_id: int | None = None


# ---------- 数据集 ----------
class DatasetCreate(BaseModel):
    name: str
    description: str = ""
    target_types: str = "prompt,rag,tool"


class CaseIn(BaseModel):
    input: str
    expected_output: str = ""
    reference_context: str = ""
    tools_spec: dict = Field(default_factory=dict)
    difficulty: str = "medium"
    tags: dict = Field(default_factory=dict)
    meta: dict = Field(default_factory=dict)


class CaseUpdate(BaseModel):
    input: str | None = None
    expected_output: str | None = None
    reference_context: str | None = None
    tools_spec: dict | None = None
    difficulty: str | None = None
    tags: dict | None = None


class ImportIn(BaseModel):
    cases: list[CaseIn]
    confirm: bool = False  # false=预检（返回问题清单不落库）


class PublishIn(BaseModel):
    note: str = ""


# ---------- 维度 ----------
class DimensionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str = ""
    rubric: str = Field(min_length=20)
    weight: float = 1.0
    applicable_types: str = ""


class DimensionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    rubric: str | None = None
    weight: float | None = None
    applicable_types: str | None = None
    enabled: bool | None = None


# ---------- 评测任务 ----------
class RunCreate(BaseModel):
    name: str
    agent_version_ids: list[int] = Field(min_length=1, max_length=2)
    dataset_version_id: int
    judge_mode: str = "single_call"
    dimension_codes: list[str] = Field(default_factory=list)
    concurrency: int = 4


# ---------- 标签 ----------
class TagCreate(BaseModel):
    category: str
    value: str
    label: str = ""


class TagUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None


# ---------- 系统 ----------
class SettingsUpdate(BaseModel):
    llm_base_url: str | None = None
    llm_model: str | None = None
    judge_model: str | None = None
    exec_concurrency: int | None = None
    pass_threshold: int | None = None
    langfuse_host: str | None = None
