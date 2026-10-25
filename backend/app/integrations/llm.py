"""LLM 工厂：统一从配置构建被测模型与 Judge 模型（OpenAI 兼容协议 / Anthropic 协议）。"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.integrations.model_profiles import temperature_allowed, thinking_kwargs


def build_llm(
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_retries: int = 2,
    thinking_level: str | None = None,
    api_format: str | None = None,
) -> BaseChatModel:
    """按供应商接口协议构建 ChatModel；参数缺省回落到全局 LLM_* 配置。

    - openai_chat（默认）：Chat Completions，思考等级按模型家族画像映射（model_profiles）
    - openai_responses：OpenAI Responses API（use_responses_api），reasoning_effort 语义同上
    - anthropic：Claude Messages API，思考走 thinking.budget_tokens（low/medium/high 分档），
      思考开启时按 Anthropic 规则剔除 temperature
    """
    model = model or settings.LLM_MODEL
    fmt = api_format or "openai_chat"
    if fmt == "anthropic":
        return _build_anthropic(
            base_url=base_url or settings.LLM_BASE_URL,
            api_key=api_key or settings.LLM_API_KEY,
            model=model,
            max_retries=max_retries,
            thinking_level=thinking_level,
        )

    extra = thinking_kwargs(model, thinking_level)
    effort = extra.pop("reasoning_effort", None)
    kwargs: dict = {"max_retries": max_retries, "timeout": 300}
    if temperature_allowed(model):
        kwargs["temperature"] = settings.LLM_TEMPERATURE if temperature is None else temperature
    if effort:
        kwargs["reasoning_effort"] = effort  # langchain-openai 一等字段，显式传参
    if extra:
        kwargs["model_kwargs"] = extra
    if fmt == "openai_responses":
        kwargs["use_responses_api"] = True
    return ChatOpenAI(
        base_url=base_url or settings.LLM_BASE_URL,
        api_key=api_key or settings.LLM_API_KEY,
        model=model,
        **kwargs,
    )


# Anthropic 思考预算分档（budget_tokens 下限 1024）；max_tokens 必须大于预算
_ANTHROPIC_BUDGET = {"low": 1024, "medium": 8192, "high": 32768}


def _build_anthropic(base_url: str, api_key: str, model: str, max_retries: int,
                     thinking_level: str | None) -> BaseChatModel:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:  # 未装依赖时给出可操作错误，而不是裸堆栈
        raise RuntimeError("anthropic 接口类型需要安装 langchain-anthropic：pip install langchain-anthropic") from e

    kwargs: dict = {"model": model, "api_key": api_key, "base_url": base_url, "max_retries": max_retries, "timeout": 300}
    if thinking_level in _ANTHROPIC_BUDGET:
        budget = _ANTHROPIC_BUDGET[thinking_level]
        # Anthropic 规则：思考开启时 temperature 必须为 1，max_tokens > budget_tokens
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        kwargs["max_tokens"] = budget + 4096
    else:
        kwargs["max_tokens"] = 4096
    return ChatAnthropic(**kwargs)


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
