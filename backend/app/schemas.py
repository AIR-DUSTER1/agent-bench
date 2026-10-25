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
    concurrency: int | None = None  # 缺省回落 settings.EXEC_CONCURRENCY
    model_id: int | None = None  # 模型覆盖（model_entry.id）；空 = 用 Agent 配置/.env 全局


class ReplayIn(BaseModel):
    """以既有 run 为模板复评：只换数据集版本，其余配置（Agent/并发/Judge）继承。"""
    dataset_version_id: int
    name: str | None = None


# ---------- 模型注册表 ----------
class ProviderCreate(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None


class ModelEntryCreate(BaseModel):
    provider_id: int
    name: str
    display_name: str = ""
    enabled: bool = True
    thinking_level: str = "high"  # off/low/medium/high，默认最高


class ModelEntryUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    enabled: bool | None = None
    provider_id: int | None = None
    thinking_level: str | None = None


# ---------- 标签 ----------
class TagCreate(BaseModel):
    category: str
    value: str
    label: str = ""


class TagUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None
