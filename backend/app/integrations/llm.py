"""LLM 工厂：统一从配置构建被测模型与 Judge 模型（OpenAI 兼容协议）。"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import settings


def build_llm(
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_retries: int = 2,
) -> BaseChatModel:
    """构建一个 ChatModel；参数缺省回落到全局 LLM_* 配置。"""
    return ChatOpenAI(
        base_url=base_url or settings.LLM_BASE_URL,
        api_key=api_key or settings.LLM_API_KEY,
        model=model or settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE if temperature is None else temperature,
        max_retries=max_retries,
        timeout=300,
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
