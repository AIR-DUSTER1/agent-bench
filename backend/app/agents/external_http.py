"""外部 HTTP Agent 适配器：把任意 HTTP 聊天服务接入评测。

支持两种协议（config.protocol）：
- learn_agent_sse：POST /api/sessions 建会话 → POST /api/chat SSE 流式返回（learn-agent 项目）
- plain_post：POST chat_url {message} → JSON 取 output_field（简单服务）
"""
from __future__ import annotations

import json
import time

import httpx

from app.agents.base import AgentOutput, BaseAgent
from app.core.config import settings


class ExternalHttpAgent(BaseAgent):
    name = "external_http"

    def __init__(self, config: dict):
        self.config = config
        self.base_url: str = config["base_url"].rstrip("/")
        self.protocol: str = config.get("protocol", "learn_agent_sse")
        self.sessions_path: str = config.get("sessions_path", "/api/sessions")
        self.chat_path: str = config.get("chat_path", "/api/chat")
        self.session_body: dict = config.get("session_body", {"kind": "agent"})
        self.auth_token: str = config.get("auth_token", "")
        self.output_field: str = config.get("output_field", "output")
        self.timeout: int = int(config.get("timeout", settings.AGENT_TIMEOUT_SECONDS))
        self._client = httpx.AsyncClient(timeout=self.timeout)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.auth_token:
            h["Authorization"] = f"Bearer {self.auth_token}"
        return h

    async def run(self, case_input: str, case: dict | None = None) -> AgentOutput:
        t0 = time.perf_counter()
        try:
            if self.protocol == "learn_agent_sse":
                return await self._run_learn_agent(case_input, t0)
            return await self._run_plain(case_input, t0)
        except Exception as e:  # noqa: BLE001
            return AgentOutput(error=f"{type(e).__name__}: {e}", latency_ms=int((time.perf_counter() - t0) * 1000))

    async def _run_learn_agent(self, case_input: str, t0: float) -> AgentOutput:
        # 1) 新建会话（每样本独立会话，保证隔离）
        resp = await self._client.post(
            self.base_url + self.sessions_path, json=self.session_body, headers=self._headers()
        )
        resp.raise_for_status()
        session_id = (resp.json().get("session") or {}).get("id") or resp.json().get("id")
        if not session_id:
            raise RuntimeError(f"建会话失败: {resp.text[:200]}")

        # 2) 发消息，解析 SSE
        text_parts: list[str] = []
        intermediate: list[dict] = []
        usage: dict = {}
        error = ""
        async with self._client.stream(
            "POST",
            self.base_url + self.chat_path,
            json={"sessionId": session_id, "message": case_input},
            headers=self._headers(),
        ) as res:
            res.raise_for_status()
            buffer = ""
            async for chunk in res.aiter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    et = ev.get("type")
                    if et == "token":
                        text_parts.append(ev.get("text", ""))
                    elif et == "tool_call":
                        intermediate.append({
                            "type": "tool_call",
                            "name": ev.get("name", ""),
                            "args": {"fragment": ev.get("argsFragment", "")},
                            "result": None, "ok": True,
                        })
                    elif et == "usage":
                        usage = {
                            "input": ev.get("inputTokens", 0),
                            "output": ev.get("outputTokens", 0),
                        }
                    elif et == "error":
                        error = str(ev.get("error") or ev.get("message") or "unknown")
        output = "".join(text_parts)
        return AgentOutput(
            output=output,
            intermediate=intermediate,
            token_usage=usage,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error=error,
            raw={"session_id": session_id},
        )

    async def _run_plain(self, case_input: str, t0: float) -> AgentOutput:
        resp = await self._client.post(
            self.base_url + self.chat_path, json={"message": case_input}, headers=self._headers()
        )
        resp.raise_for_status()
        data = resp.json()
        return AgentOutput(
            output=str(data.get(self.output_field, "")),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
