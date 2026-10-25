"""Prompt Agent（纯推理）：LCEL 链 ChatPromptTemplate | llm | StrOutputParser。"""
from __future__ import annotations

import time

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.agents.base import AgentOutput, BaseAgent
from app.integrations.llm import build_llm

DEFAULT_SYSTEM = "你是一个严谨的企业级智能助手。请准确理解并完成用户指令，遵守输出格式要求。"


class PromptAgent(BaseAgent):
    name = "prompt"

    def __init__(self, config: dict):
        self.config = config
        self.llm = build_llm(
            base_url=config.get("base_url"),
            api_key=config.get("api_key"),
            model=config.get("model"),
            temperature=config.get("temperature", 0.0),
        )
        self.system = config.get("system_prompt", DEFAULT_SYSTEM)
        self.few_shot: list[dict] = config.get("few_shot", [])

    async def run(self, case_input: str, case: dict | None = None) -> AgentOutput:
        t0 = time.perf_counter()
        messages = [("system", self.system)]
        for shot in self.few_shot:
            messages.append(("human", shot.get("q", "")))
            messages.append(("ai", shot.get("a", "")))
        messages.append(("human", "{input}"))
        chain = ChatPromptTemplate.from_messages(messages) | self.llm | StrOutputParser()
        try:
            out = await chain.ainvoke({"input": case_input})
            usage = {}
            # langchain 用量回调较重，v1 以字符数近似并留接口；如需精确用量可接 Langfuse
            usage = {"input_chars": len(case_input), "output_chars": len(out)}
            return AgentOutput(
                output=out,
                intermediate=[{"type": "llm_call", "model": self.llm.model_name}],
                token_usage=usage,
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        except Exception as e:  # noqa: BLE001
            return AgentOutput(error=str(e), latency_ms=int((time.perf_counter() - t0) * 1000))
