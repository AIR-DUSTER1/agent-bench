"""系统路由：健康检查 + 配置查看（密钥脱敏）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "llm_configured": bool(settings.LLM_API_KEY),
        "llm_model": settings.LLM_MODEL,
        "judge_model": settings.judge_model,
        "langfuse_enabled": settings.langfuse_enabled,
        "trace_mode": "langfuse" if settings.langfuse_enabled else "local-json",
    }


@router.get("/settings")
def get_settings():
    def mask(v: str) -> str:
        return (v[:6] + "***") if v and len(v) > 10 else ("***" if v else "")

    return {
        "llm_base_url": settings.LLM_BASE_URL,
        "llm_model": settings.LLM_MODEL,
        "llm_api_key_masked": mask(settings.LLM_API_KEY),
        "judge_base_url": settings.judge_base_url,
        "judge_model": settings.judge_model,
        "judge_api_key_masked": mask(settings.judge_api_key),
        "exec_concurrency": settings.EXEC_CONCURRENCY,
        "judge_concurrency": settings.JUDGE_CONCURRENCY,
        "pass_threshold": settings.PASS_THRESHOLD,
        "langfuse_host": settings.LANGFUSE_HOST,
        "langfuse_enabled": settings.langfuse_enabled,
        "database_url_masked": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else settings.DATABASE_URL,
    }
