"""常见模型的参数画像匹配：同一个"思考等级"在不同供应商的参数形态不同。

best-effort 设计：按模型名匹配家族，决定思考参数的写法与 temperature 是否可设。
- 已实测：deepseek 家族接受 reasoning_effort（2026-10-25，响应含 reasoning_tokens）。
- 未命中画像的模型一律不发思考参数（宁缺勿错——严格网关遇到未知参数会 400）；
  新模型接入时在此登记一行即可。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    family: str
    thinking_style: str  # reasoning_effort | enable_thinking | thinking_type | none
    supports_temperature: bool = True


_PROFILES: tuple[tuple[str, ModelProfile], ...] = (
    # OpenAI 系：o 系与 gpt-5 只接受默认 temperature；gpt-4 及更早无思考参数
    (r"^o\d", ModelProfile("openai-o", "reasoning_effort", supports_temperature=False)),
    (r"^gpt-5", ModelProfile("openai-gpt5", "reasoning_effort", supports_temperature=False)),
    (r"^gpt-", ModelProfile("openai-gpt4", "none")),
    # 国产主流
    (r"deepseek", ModelProfile("deepseek", "reasoning_effort")),
    (r"qwen|qwq|qvq", ModelProfile("qwen", "enable_thinking")),  # 注意：enable_thinking 在部分 Qwen3 通道仅流式可用
    (r"glm|chatglm|zhipu", ModelProfile("glm", "thinking_type")),
    (r"doubao", ModelProfile("doubao", "thinking_type")),  # 火山方舟兼容层支持 thinking.type
    (r"ernie", ModelProfile("ernie", "none")),
    (r"hunyuan", ModelProfile("hunyuan", "none")),
    (r"moonshot|kimi", ModelProfile("moonshot", "none")),  # Kimi 思考由模型变体决定（k2-thinking 等）
    (r"minimax|abab", ModelProfile("minimax", "none")),
    (r"spark", ModelProfile("spark", "none")),
    (r"baichuan", ModelProfile("baichuan", "none")),
    (r"^yi-", ModelProfile("yi", "none")),
    (r"step-", ModelProfile("step", "none")),
    (r"internlm", ModelProfile("internlm", "none")),
    (r"minicpm", ModelProfile("minicpm", "none")),
    # 海外
    (r"^gemini", ModelProfile("gemini", "reasoning_effort")),
    (r"grok", ModelProfile("grok", "reasoning_effort")),
    (r"claude", ModelProfile("claude", "none")),  # 思考由 Anthropic 原生 thinking budget 控制（见 llm._build_anthropic）
    (r"llama", ModelProfile("llama", "none")),
    (r"mistral|magistral|ministral|mixtral|pixtral", ModelProfile("mistral", "none")),
    (r"command", ModelProfile("cohere", "none")),
    (r"^gemma", ModelProfile("gemma", "none")),
    (r"phi-", ModelProfile("phi", "none")),
    (r"nova", ModelProfile("nova", "none")),
)
# 兜底画像：未登记家族不发思考参数（严格网关遇未知参数会 400），temperature 保持可配
_UNKNOWN = ModelProfile("unknown", "none")


def match_model_profile(model_name: str) -> ModelProfile:
    for pattern, profile in _PROFILES:
        if re.search(pattern, model_name or "", re.IGNORECASE):
            return profile
    return _UNKNOWN


def thinking_kwargs(model_name: str, thinking_level: str | None) -> dict:
    """把思考等级翻译成该模型家族的请求参数。

    level 为空 = 用户未配置，不动模型默认；off 的语义随家族：
    reasoning_effort 无法表达关闭则不发送，enable_thinking/thinking_type 显式关闭。
    """
    if not thinking_level:
        return {}
    profile = match_model_profile(model_name)
    off = thinking_level == "off"
    if profile.thinking_style == "reasoning_effort":
        return {} if off else {"reasoning_effort": thinking_level}
    if profile.thinking_style == "enable_thinking":
        return {"enable_thinking": not off}
    if profile.thinking_style == "thinking_type":
        return {"thinking": {"type": "disabled" if off else "enabled"}}
    return {}


def temperature_allowed(model_name: str) -> bool:
    """o 系 / gpt-5 等只接受默认 temperature，传 0.0 会被 API 拒绝。"""
    return match_model_profile(model_name).supports_temperature
