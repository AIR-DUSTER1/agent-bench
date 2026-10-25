"""Agent 统一抽象。

所有 Agent（内置三类 + 外部适配器）实现 `async def run(case_input, case) -> AgentOutput`。
intermediate（中间轨迹）是归因分析的数据基础，格式约定：
  [{"type":"retrieval","query":...,"docs":[{"title":...,"text":...,"score":...}]}]
  [{"type":"tool_call","name":...,"args":{...},"result":...,"ok":true|false}]
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentOutput:
    output: str = ""
    intermediate: list[dict] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)  # {"input":..,"output":..}
    latency_ms: int = 0
    error: str = ""
    raw: dict = field(default_factory=dict)


class BaseAgent:
    """子类需实现 run()。"""

    name = "base"

    async def run(self, case_input: str, case: dict | None = None) -> AgentOutput:
        raise NotImplementedError

    async def aclose(self) -> None:  # 外部适配器用于释放连接
        return None


def build_agent(agent_type: str, config: dict):
    """根据 Agent 类型与版本配置构建实例。"""
    if agent_type == "prompt":
        from app.agents.prompt_agent import PromptAgent

        return PromptAgent(config)
    if agent_type == "rag":
        from app.agents.rag_agent import RagAgent

        return RagAgent(config)
    if agent_type == "tool":
        from app.agents.tool_agent import ToolAgent

        return ToolAgent(config)
    if agent_type == "external_http":
        from app.agents.external_http import ExternalHttpAgent

        return ExternalHttpAgent(config)
    if agent_type == "external_cli":
        from app.agents.external_cli import ExternalCliAgent

        return ExternalCliAgent(config)
    raise ValueError(f"未知 Agent 类型: {agent_type}")
