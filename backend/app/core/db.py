"""数据库引擎、会话与建表（只负责 schema，不依赖业务引擎层——种子数据见 app/bootstrap.py）。"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)

if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（幂等）+ 轻量加列迁移（幂等）。导入 app.models 触发全部模型注册后再 create_all。"""
    from app import models  # noqa: F401  确保模型全部注册

    models.Base.metadata.create_all(engine)
    _ensure_columns(
        engine,
        "case_result",
        {"judge_usage": "TEXT DEFAULT '{}'"},
    )
    _ensure_columns(
        engine,
        "eval_run",
        {"model_id": "INTEGER"},
    )
    _ensure_columns(
        engine,
        "model_entry",
        {"thinking_level": "VARCHAR(16) DEFAULT 'high'"},
    )
    _ensure_columns(
        engine,
        "model_provider",
        {"api_format": "VARCHAR(32) DEFAULT 'openai_chat'"},
    )


def _ensure_columns(target_engine, table: str, columns: dict[str, str]) -> None:
    """对既有库补加新列（create_all 不会改老表）。SQLite/MySQL 通用。"""
    from sqlalchemy import inspect, text

    inspector = inspect(target_engine)
    if table not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(table)}
    with target_engine.begin() as conn:
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
