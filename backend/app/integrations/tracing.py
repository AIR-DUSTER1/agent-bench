"""追踪集成：Langfuse 可用则上报；否则降级为本地 JSON Trace（保证系统可独立运行）。

本地 Trace 落盘路径：data/traces/<run_id>/<agent_version_id>_<case_seq>.json
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings

_langfuse = None
_langfuse_failed = False


def _get_langfuse():
    global _langfuse, _langfuse_failed
    if _langfuse_failed or not settings.langfuse_enabled:
        return None
    if _langfuse is None:
        try:
            from langfuse import Langfuse

            _langfuse = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
            )
        except Exception:
            _langfuse_failed = True
            return None
    return _langfuse


def make_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def record_trace(
    run_id: int | str,
    case_result_key: str,
    *,
    name: str,
    input_data: Any,
    output_data: Any,
    metadata: dict | None = None,
    latency_ms: int = 0,
    tags: list[str] | None = None,
) -> str:
    """记录一次 Agent 执行 / Judge 调用。返回 trace_id（本地模式返回本地 id）。"""
    trace_id = make_trace_id()

    # 1) Langfuse 上报（配置了才启用）
    lf = _get_langfuse()
    if lf is not None:
        try:
            lf.trace(
                id=trace_id,
                name=name,
                input=input_data,
                output=output_data,
                metadata=metadata or {},
                tags=tags or [],
            )
            return trace_id
        except Exception:
            pass  # 上报失败不影响评测主流程

    # 2) 本地降级：JSON 落盘
    d: Path = settings.trace_dir / str(run_id)
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "trace_id": trace_id,
        "name": name,
        "ts": datetime.now(timezone.utc).isoformat(),
        "input": input_data,
        "output": output_data,
        "metadata": metadata or {},
        "latency_ms": latency_ms,
        "tags": tags or [],
    }
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(case_result_key))
    (d / f"{safe}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    return trace_id


def flush_langfuse() -> None:
    if _langfuse is not None:
        try:
            _langfuse.flush()
        except Exception:
            pass
