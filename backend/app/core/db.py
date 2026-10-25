"""数据库会话与初始化。"""
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
    """建表 + 写入内置维度与标签字典（幂等）。"""
    from app import models  # noqa: F401  确保模型全部注册
    from app.models import Base
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session
    from app.evaluation.rubrics import BUILTIN_DIMENSIONS
    from app.governance.tags import BUILTIN_TAG_DICT

    with SessionLocal() as db:  # type: Session
        Dimension, TagDict = models.Dimension, models.TagDict
        for d in BUILTIN_DIMENSIONS:
            if not db.query(Dimension).filter_by(code=d["code"]).first():
                db.add(Dimension(**d, is_builtin=True))
        for t in BUILTIN_TAG_DICT:
            if not db.query(TagDict).filter_by(category=t["category"], value=t["value"]).first():
                db.add(TagDict(**t))
        db.commit()
