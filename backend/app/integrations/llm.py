"""LLM 工厂：统一从配置构建被测模型与 Judge 模型（OpenAI 兼容协议）。"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import settings


def build_llm(
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_retries: int = 2,
    thinking_level: str | None = None,
) -> BaseChatModel:
    """构建一个 ChatModel；参数缺省回落到全局 LLM_* 配置。

    thinking_level（off/low/medium/high）映射为 OpenAI 兼容 reasoning_effort 参数；
    off/未设置不发送该参数（走模型服务端默认行为）。
    """
    extra: dict = {}
    if thinking_level and thinking_level != "off":
        extra["reasoning_effort"] = thinking_level  # langchain-openai 一等字段，显式传参
    return ChatOpenAI(
        base_url=base_url or settings.LLM_BASE_URL,
        api_key=api_key or settings.LLM_API_KEY,
        model=model or settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE if temperature is None else temperature,
        max_retries=max_retries,
        timeout=300,
        **extra,
    )


def build_judge_llm() -> BaseChatModel:
    """Judge 模型：强制 JSON 输出模式（OpenAI 兼容网关普遍支持），降低结构化解析失败率。"""
    return ChatOpenAI(
        base_url=settings.judge_base_url,
        api_key=settings.judge_api_key,
        model=settings.judge_model,
        temperature=0.0,
        max_retries=2,
        timeout=300,
        model_kwargs={"response_format": {"type": "json_object"}},
    )


def extract_usage(resp: Any) -> dict:
    """从 LLM 响应（AIMessage 等）提取 token 用量，统一键名 input_tokens/output_tokens/total_tokens。
    模型未上报时返回 {}，由 metrics.normalize_usage 降级处理（不得硬造数字）。"""
    um = getattr(resp, "usage_metadata", None)
    if not isinstance(um, dict):
        return {}
    out: dict[str, int] = {}
    for k in ("input_tokens", "output_tokens", "total_tokens"):
        v = um.get(k)
        if isinstance(v, (int, float)):
            out[k] = int(v)
    return out
