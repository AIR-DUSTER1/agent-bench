"""Agent-Bench 后端入口：API 组装 + 控制台静态页 + 启动初始化。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import agents, datasets, dimensions, governance, runs, system
from app.bootstrap import seed_builtin_data
from app.core.config import BASE_DIR, settings
from app.core.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_builtin_data()
    yield


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

# CORS 仅在显式配置白名单时启用（默认同源访问，无跨域面）
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """可选 Bearer 鉴权：AUTH_TOKEN 配置后，除健康检查外的 /api/* 一律校验。"""
    if (
        settings.AUTH_TOKEN
        and request.url.path.startswith("/api")
        and request.url.path != "/api/system/health"
        and request.headers.get("authorization") != f"Bearer {settings.AUTH_TOKEN}"
    ):
        return JSONResponse({"detail": "unauthorized：缺少或错误的 Bearer token"}, status_code=401)
    return await call_next(request)

for r in (system, agents, datasets, dimensions, runs, governance):
    app.include_router(r.router)

# 内置轻量控制台（M6）
static_dir = BASE_DIR / "app" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def console():
        return FileResponse(static_dir / "index.html")
