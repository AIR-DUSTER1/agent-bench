"""RAG Agent（检索增强）：BM25 检索 + 引用生成，执行时记录召回列表供归因。"""
from __future__ import annotations

import time
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from app.agents.base import AgentOutput, BaseAgent
from app.agents.retrieval import BM25Store, load_kb
from app.integrations.llm import build_llm, extract_usage

DEFAULT_KB_DIR = Path(__file__).resolve().parents[3] / "seed" / "kb"

PROMPT = """你是企业知识库问答助手。仅依据下面的「检索到的资料」回答问题；
资料中没有的内容要明确说明「知识库中未找到」，不得编造。回答末尾用一行标注引用来源标题。

检索到的资料：
{context}

问题：{question}"""


class RagAgent(BaseAgent):
    name = "rag"

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
        self.top_k: int = int(config.get("top_k", 3))
        kb_dir = config.get("kb_dir") or DEFAULT_KB_DIR
        self.store: BM25Store = load_kb(kb_dir) or BM25Store()
        self._loaded_from = str(kb_dir)

    async def run(self, case_input: str, case: dict | None = None) -> AgentOutput:
        t0 = time.perf_counter()
        hits = self.store.search(case_input, k=self.top_k)
        context = "\n\n".join(f"【{h['title']}】\n{h['text']}" for h, _s in hits) or "（未检索到任何资料）"
        chain = ChatPromptTemplate.from_template(PROMPT) | self.llm
        try:
            resp = await chain.ainvoke({"context": context, "question": case_input})
            out = resp.content if isinstance(resp.content, str) else str(resp.content)
            inter = [{
                "type": "retrieval",
                "query": case_input,
                "top_k": self.top_k,
                "docs": [{"title": h["title"], "score": s, "excerpt": h["text"][:200]} for h, s in hits],
            }]
            return AgentOutput(
                output=out,
                intermediate=inter,
                token_usage={
                    **extract_usage(resp),
                    "input_chars": len(context) + len(case_input),
                    "output_chars": len(out),
                },
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw={"kb_docs": len(self.store.docs), "kb_dir": self._loaded_from},
            )
        except Exception as e:  # noqa: BLE001
            return AgentOutput(error=str(e), latency_ms=int((time.perf_counter() - t0) * 1000))
