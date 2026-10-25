"""单次试跑服务：构建 → 执行 → 释放，供 API/脚本复用（api 层不内嵌编排逻辑）。"""
from __future__ import annotations

from app.agents.base import AgentOutput, build_agent


async def try_run(agent_type: str, config: dict, case_input: str) -> dict:
    """构建指定类型 Agent 执行一次输入并返回可序列化结果；任何异常都归入 error 字段。"""
    agent = build_agent(agent_type, config)
    try:
        out: AgentOutput = await agent.run(case_input)
    except Exception as e:  # noqa: BLE001 失败归一化，试跑端点不应 5xx
        out = AgentOutput(error=f"{type(e).__name__}: {e}")
    finally:
        await agent.aclose()
    return {
        "output": out.output,
        "error": out.error,
        "intermediate": out.intermediate,
        "latency_ms": out.latency_ms,
        "token_usage": out.token_usage,
    }
