"""组合根的启动种子：内置评测维度与标签字典（幂等）。

放本模块而非 core/db.py，是因为种子数据来自引擎层（rubrics/tags），
core 层禁止反向依赖引擎层（见 AGENTS.md §1）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.evaluation.rubrics import BUILTIN_DIMENSIONS
from app.governance.tags import BUILTIN_TAG_DICT
from app.models import Dimension, TagDict


def seed_builtin_data(db: Session | None = None) -> None:
    """写入内置维度与标签字典；已存在则跳过。幂等，可重复调用。"""
    if db is not None:
        _seed(db)
        return
    with SessionLocal() as session:
        _seed(session)


def _seed(db: Session) -> None:
    for d in BUILTIN_DIMENSIONS:
        if not db.query(Dimension).filter_by(code=d["code"]).first():
            db.add(Dimension(**d, is_builtin=True))
    for t in BUILTIN_TAG_DICT:
        if not db.query(TagDict).filter_by(category=t["category"], value=t["value"]).first():
            db.add(TagDict(**t))
    db.commit()
