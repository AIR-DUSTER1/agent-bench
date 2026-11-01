"""外部 HTTP Agent 适配器：把任意 HTTP 聊天服务接入评测。

支持两种协议（config.protocol）：
- learn_agent_sse：POST /api/sessions 建会话 → POST /api/chat SSE 流式返回（learn-agent/agent-atlas 项目）
- plain_post：POST chat_url {message} → JSON 取 output_field（简单服务）

可选 config.session_permission：建会话后立即设置会话权限模式
（POST {sessions_path}/{id}/permission {"mode": ...}，用于带审批流的 Agent 在无人值守评测中放开执行）。
可选 config.headless：为 True 时 POST /api/chat 额外携带 {"headless": true}
（agent-atlas 0.9.0-beta.2+：澄清不挂起等 resume，自动采用默认假设继续执行）。
429 语义：并发闸繁忙时服务端回 429 + Retry-After（agent-atlas 0.9.0-beta.2+），
本适配器按该头重试（config.busy_retries 控制次数，默认 5，单次等待上限 30s）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from app.agents.base import AgentOutput, BaseAgent
from app.core.config import settings

logger = logging.getLogger(__name__)

_RETRY_AFTER_DEFAULT_SECONDS = 2.0
_RETRY_AFTER_CAP_SECONDS = 30.0
_BUSY_RETRIES_DEFAULT = 5


class ExternalHttpAgent(BaseAgent):
    name = "external_http"

    def __init__(self, config: dict):
        self.config = config
        self.base_url: str = config["base_url"].rstrip("/")
        self.protocol: str = config.get("protocol", "learn_agent_sse")
        self.sessions_path: str = config.get("sessions_path", "/api/sessions")
        self.chat_path: str = config.get("chat_path", "/api/chat")
        self.session_body: dict = config.get("session_body", {"kind": "agent"})
        self.session_permission: str = config.get("session_permission", "")
        self.headless: bool = bool(config.get("headless", False))
        self.auth_token: str = config.get("auth_token", "")
        self.output_field: str = config.get("output_field", "output")
        self.timeout: int = int(config.get("timeout", settings.AGENT_TIMEOUT_SECONDS))
        self.busy_retries: int = int(config.get("busy_retries", _BUSY_RETRIES_DEFAULT))
        self._client = httpx.AsyncClient(timeout=self.timeout)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.auth_token:
            h["Authorization"] = f"Bearer {self.auth_token}"
        return h

    def _retry_delay(self, response: httpx.Response | None) -> float:
        """429 重试等待：优先服务端 Retry-After（秒），缺失/非法用默认值，封顶防呆。"""
        if response is None:
            return _RETRY_AFTER_DEFAULT_SECONDS
        try:
            delay = float(response.headers.get("Retry-After", "") or _RETRY_AFTER_DEFAULT_SECONDS)
        except (TypeError, ValueError):
            delay = _RETRY_AFTER_DEFAULT_SECONDS
        return min(max(delay, 0.0), _RETRY_AFTER_CAP_SECONDS)

    async def run(self, case_input: str, case: dict | None = None) -> AgentOutput:
        t0 = time.perf_counter()
        try:
            if self.protocol == "learn_agent_sse":
                return await self._run_learn_agent(case_input, t0)
            return await self._run_plain(case_input, t0)
        except httpx.HTTPStatusError as e:
            # 非 2xx 时把服务端的错误 body 带回来（只看状态码无法定位，如 400 的具体原因）
            body = e.response.text[:300] if e.response is not None else ""
            return AgentOutput(error=f"{e.response.status_code if e.response is not None else 'HTTP'}: {body}",
                               latency_ms=int((time.perf_counter() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return AgentOutput(error=f"{type(e).__name__}: {e}", latency_ms=int((time.perf_counter() - t0) * 1000))

    async def _run_learn_agent(self, case_input: str, t0: float) -> AgentOutput:
        # 1) 新建会话（每样本独立会话，保证隔离）；429 按 Retry-After 重试
        for attempt in range(self.busy_retries + 1):
            resp = await self._client.post(
                self.base_url + self.sessions_path, json=self.session_body, headers=self._headers()
            )
            if resp.status_code == 429 and attempt < self.busy_retries:
                await asyncio.sleep(self._retry_delay(resp))
                continue
            break
        resp.raise_for_status()
        session_id = (resp.json().get("session") or {}).get("id") or resp.json().get("id")
        if not session_id:
            raise RuntimeError(f"建会话失败: {resp.text[:200]}")

        # 2) 可选：设置会话权限模式（带审批流的 Agent 无人值守评测时放开执行）
        #    权限设置失败只记日志不中断——部分实现没有该端点
        if self.session_permission:
            perm = await self._client.post(
                f"{self.base_url}{self.sessions_path}/{session_id}/permission",
                json={"mode": self.session_permission}, headers=self._headers(),
            )
            if perm.status_code >= 400:
                logger.warning("会话权限设置被拒（%s），按默认权限继续", perm.status_code)
        # 2) 发消息，解析 SSE；429（并发闸繁忙）按 Retry-After 重试整条流
        text_parts: list[str] = []
        intermediate: list[dict] = []
        usage: dict = {}
        saw_task_usage = False
        error = ""
        chat_body: dict = {"sessionId": session_id, "message": case_input}
        if self.headless:
            chat_body["headless"] = True
        for attempt in range(self.busy_retries + 1):
            try:
                async with self._client.stream(
                    "POST",
                    self.base_url + self.chat_path,
                    json=chat_body,
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
                            elif et == "task_usage":
                                # 轮末任务级终值（含内部辅助调用），优先于每调用快照
                                saw_task_usage = True
                                usage = {
                                    "input": ev.get("inputTokens", 0),
                                    "output": ev.get("outputTokens", 0),
                                }
                            elif et == "usage":
                                if not saw_task_usage:
                                    usage = {
                                        "input": ev.get("inputTokens", 0),
                                        "output": ev.get("outputTokens", 0),
                                    }
                            elif et == "error":
                                error = str(ev.get("error") or ev.get("message") or "unknown")
                break
            except httpx.HTTPStatusError as e:
                retryable = e.response is not None and e.response.status_code == 429
                if not retryable or attempt >= self.busy_retries:
                    raise
                delay = self._retry_delay(e.response)
                logger.info("评测会话繁忙（429），%.1fs 后重试（第 %d/%d 次）", delay, attempt + 1, self.busy_retries)
                await asyncio.sleep(delay)
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
