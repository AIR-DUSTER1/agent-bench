"""Tool Agent（工具调用）：langchain 1.x create_agent + 内置工具集，记录完整工具轨迹。"""
from __future__ import annotations

import time

from langchain_core.messages import AIMessage, ToolMessage

from app.agents.base import AgentOutput, BaseAgent
from app.agents.tools.builtin import BUILTIN_TOOLS
from app.integrations.llm import build_llm

DEFAULT_SYSTEM = (
    "你是一个能调用工具完成任务的智能助手。可用工具：sql_query（演示业务库查询）、"
    "calculator（数学计算）、knowledge_search（企业知识库检索）。"
    "涉及数据库数值、精确计算或公司制度的问题必须调用工具获取事实，不得凭记忆编造。"
)


class ToolAgent(BaseAgent):
    name = "tool"

    def __init__(self, config: dict):
        self.config = config
        from langchain.agents import create_agent

        llm = build_llm(
            base_url=config.get("base_url"),
            api_key=config.get("api_key"),
            model=config.get("model"),
            temperature=config.get("temperature", 0.0),
            thinking_level=config.get("thinking_level"),
            api_format=config.get("api_format"),
        )
        tool_names = config.get("tools", list(BUILTIN_TOOLS.keys()))
        tools = [BUILTIN_TOOLS[n] for n in tool_names if n in BUILTIN_TOOLS]
        self.agent = create_agent(llm, tools, system_prompt=config.get("system_prompt", DEFAULT_SYSTEM))
        self.max_steps = int(config.get("max_steps", 8))

    async def run(self, case_input: str, case: dict | None = None) -> AgentOutput:
        t0 = time.perf_counter()
        try:
            result = await self.agent.ainvoke(
                {"messages": [("user", case_input)]},
                config={"recursion_limit": self.max_steps * 2 + 4},
            )
            messages = result.get("messages", [])
            intermediate: list[dict] = []
            by_call_id: dict[str, dict] = {}
            final_text = ""
            usage: dict = {}
            for m in messages:
                if isinstance(m, AIMessage):
                    for tc in getattr(m, "tool_calls", None) or []:
                        item = {
                            "type": "tool_call",
                            "name": tc.get("name", ""),
                            "args": tc.get("args", {}),
                            "ok": True,
                            "result": None,
                        }
                        intermediate.append(item)
                        if tc.get("id"):
                            by_call_id[tc["id"]] = item
                    if isinstance(m.content, str) and m.content.strip() and not getattr(m, "tool_calls", None):
                        final_text = m.content
                    um = getattr(m, "usage_metadata", None)
                    if um:
                        usage = {"input": um.get("input_tokens", 0), "output": um.get("output_tokens", 0)}
                elif isinstance(m, ToolMessage):
                    item = by_call_id.get(m.tool_call_id)
                    content = str(m.content)
                    if item is not None:
                        item["result"] = content[:2000]
                        item["ok"] = not content.startswith("ERROR")
            return AgentOutput(
                output=final_text,
                intermediate=intermediate,
                token_usage=usage,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw={"steps": len(messages)},
            )
        except Exception as e:  # noqa: BLE001
            return AgentOutput(error=str(e), latency_ms=int((time.perf_counter() - t0) * 1000))
