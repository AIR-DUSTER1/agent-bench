"""Agent-Bench 后端入口：API 组装 + 控制台静态页 + 启动初始化。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (system, agents, datasets, dimensions, runs, governance):
    app.include_router(r.router)

# 内置轻量控制台（M6）
static_dir = BASE_DIR / "app" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def console():
        return FileResponse(static_dir / "index.html")
