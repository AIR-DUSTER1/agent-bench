"""外部 CLI Agent 适配器：以子进程方式一次性调用 CLI Agent（如 deepseek-harness 的 dsh headless）。

config:
  argv: ["dsh", "--profile", "headless", "{input}"]   # {input} 占位符整体替换为一条 argv
  cwd: 工作目录（可选）
  timeout: 秒（默认 settings.AGENT_TIMEOUT_SECONDS）
  stdin_mode: true 时把输入写进 stdin 而不是 argv

Windows 说明：npm 全局命令是 .cmd/.ps1 shim，create_subprocess_exec 不会按 PATHEXT 解析，
这里用 shutil.which 解析真实路径；.cmd/.bat 经 cmd.exe /c 执行。
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import time

from app.agents.base import AgentOutput, BaseAgent
from app.core.config import settings


def _resolve_argv(argv: list[str]) -> list[str]:
    """Windows 下把 npm shim（dsh → dsh.cmd）解析为可被 exec 的命令。"""
    exe = shutil.which(argv[0])
    if exe is None:
        return argv
    if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe, *argv[1:]]
    return [exe, *argv[1:]]


class ExternalCliAgent(BaseAgent):
    name = "external_cli"

    def __init__(self, config: dict):
        self.config = config
        self.argv_template: list[str] = config["argv"]
        self.cwd: str | None = config.get("cwd")
        self.timeout: int = int(config.get("timeout", settings.AGENT_TIMEOUT_SECONDS))
        self.stdin_mode: bool = bool(config.get("stdin_mode", False))

    async def run(self, case_input: str, case: dict | None = None) -> AgentOutput:
        t0 = time.perf_counter()
        argv = [case_input if a == "{input}" else a for a in self.argv_template]
        try:
            proc = await asyncio.create_subprocess_exec(
                *_resolve_argv(argv),
                cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if self.stdin_mode else asyncio.subprocess.DEVNULL,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    (proc.communicate(case_input.encode("utf-8") if self.stdin_mode else None)),
                    timeout=self.timeout,
                )
            except TimeoutError:
                proc.kill()
                return AgentOutput(
                    error=f"CLI 执行超时（>{self.timeout}s）",
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            output = stdout_b.decode("utf-8", errors="replace").strip()
            stderr = stderr_b.decode("utf-8", errors="replace").strip()
            ok = proc.returncode == 0
            return AgentOutput(
                output=output,
                intermediate=[{
                    "type": "cli_call", "argv": argv[:2] + ["..."], "returncode": proc.returncode,
                }],
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error="" if ok else f"exit={proc.returncode}: {stderr[-500:]}",
            )
        except Exception as e:  # noqa: BLE001
            return AgentOutput(error=f"{type(e).__name__}: {e}", latency_ms=int((time.perf_counter() - t0) * 1000))
