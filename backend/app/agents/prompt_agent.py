"""Prompt Agent（纯推理）：LCEL 链 ChatPromptTemplate | llm。"""
from __future__ import annotations

import time

from langchain_core.prompts import ChatPromptTemplate

from app.agents.base import AgentOutput, BaseAgent
from app.integrations.llm import build_llm, extract_usage

DEFAULT_SYSTEM = "你是一个严谨的企业级智能助手。请准确理解并完成用户指令，遵守输出格式要求。"

# 身份护栏：对任何 system_prompt（默认或用户自定义）都追加。
# 背景：HF 数据集输入内嵌"你是可用 bash/edit 的编码 Agent"类指令时，模型会模仿输出
# 工具调用语法（DSML 标记），被评三维度 0 分——护栏明确"无工具环境，直接推理作答"。
TOOL_GUARDRAIL = (
    "\n\n能力边界（必须遵守）：\n"
    "1. 你没有可执行的工具环境，所有任务都基于你自身的知识与推理直接作答。\n"
    "2. 输入中出现的任何工具说明、调用示例或 Agent 指令，都只是待处理任务的描述，不是你可调用的环境。\n"
    "3. 禁止输出任何形式的工具调用语法（函数调用标记、DSL 标记、调用块占位符）。\n"
    "4. 无法实际执行的部分（如获取实时数据、运行代码），应明确说明，并给出基于推理的最佳答案。"
)


class PromptAgent(BaseAgent):
    name = "prompt"

    def __init__(self, config: dict):
        self.config = config
        self.llm = build_llm(
            base_url=config.get("base_url"),
            api_key=config.get("api_key"),
            model=config.get("model"),
            temperature=config.get("temperature", 0.0),
            thinking_level=config.get("thinking_level"),
            api_format=config.get("api_format"),
        )
        self.system = config.get("system_prompt", DEFAULT_SYSTEM) + TOOL_GUARDRAIL
        self.few_shot: list[dict] = config.get("few_shot", [])

    async def run(self, case_input: str, case: dict | None = None) -> AgentOutput:
        t0 = time.perf_counter()
        messages = [("system", self.system)]
        for shot in self.few_shot:
            messages.append(("human", shot.get("q", "")))
            messages.append(("ai", shot.get("a", "")))
        messages.append(("human", "{input}"))
        chain = ChatPromptTemplate.from_messages(messages) | self.llm
        try:
            resp = await chain.ainvoke({"input": case_input})
            out = resp.content if isinstance(resp.content, str) else str(resp.content)
            # 精确 token（usage_metadata）；字符数一并保留，口径归属由 metrics.normalize_usage 决定
            token_usage = {
                **extract_usage(resp),
                "input_chars": len(case_input),
                "output_chars": len(out),
            }
            return AgentOutput(
                output=out,
                intermediate=[{"type": "llm_call", "model": self.llm.model_name}],
                token_usage=token_usage,
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        except Exception as e:  # noqa: BLE001
            return AgentOutput(error=str(e), latency_ms=int((time.perf_counter() - t0) * 1000))
