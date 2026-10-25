"""Agent 管理路由（薄层：校验 → 调引擎/服务 → 组装响应）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runner import try_run
from app.core.db import get_db
from app.models import AGENT_TYPES, Agent, AgentVersion
from app.schemas import AgentCreate, AgentTestInput, AgentVersionCreate

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _agent_out(a: Agent) -> dict:
    return {
        "id": a.id, "name": a.name, "description": a.description, "type": a.type,
        "versions": [
            {"id": v.id, "version": v.version, "config": json.loads(v.config),
             "note": v.note, "created_at": v.created_at.isoformat()}
            for v in a.versions
        ],
    }


def _get_agent_or_404(db: Session, agent_id: int) -> Agent:
    a = db.get(Agent, agent_id)
    if not a:
        raise HTTPException(404, "agent 不存在")
    return a


@router.get("")
def list_agents(db: Session = Depends(get_db)) -> list[dict]:
    return [_agent_out(a) for a in db.execute(select(Agent).order_by(Agent.id)).scalars()]


@router.post("", status_code=201)
def create_agent(body: AgentCreate, db: Session = Depends(get_db)) -> dict:
    if body.type not in AGENT_TYPES:
        raise HTTPException(400, f"type 必须是 {AGENT_TYPES}")
    if db.query(Agent).filter_by(name=body.name).first():
        raise HTTPException(409, f"Agent 名称已存在: {body.name}")
    a = Agent(name=body.name, description=body.description, type=body.type)
    db.add(a)
    db.flush()
    db.add(AgentVersion(agent_id=a.id, version="v1",
                        config=json.dumps(body.config, ensure_ascii=False), note=body.note))
    db.commit()
    return _agent_out(db.get(Agent, a.id))


@router.get("/{agent_id}")
def get_agent(agent_id: int, db: Session = Depends(get_db)) -> dict:
    return _agent_out(_get_agent_or_404(db, agent_id))


@router.post("/{agent_id}/versions", status_code=201)
def add_version(agent_id: int, body: AgentVersionCreate, db: Session = Depends(get_db)) -> dict:
    a = _get_agent_or_404(db, agent_id)
    nums = [int(v.version.lstrip("v")) for v in (x.version for x in a.versions)]
    new_v = f"v{max(nums, default=0) + 1}"
    av = AgentVersion(agent_id=a.id, version=new_v,
                      config=json.dumps(body.config, ensure_ascii=False), note=body.note)
    db.add(av)
    db.commit()
    return {"id": av.id, "version": av.version}


@router.post("/{agent_id}/test")
async def test_agent(agent_id: int, body: AgentTestInput, db: Session = Depends(get_db)) -> dict:
    """单样本试跑最新（或指定）版本。"""
    a = _get_agent_or_404(db, agent_id)
    versions = sorted(a.versions, key=lambda v: v.id)
    av = db.get(AgentVersion, body.version_id) if body.version_id else versions[-1]
    if not av or av.agent_id != a.id:
        raise HTTPException(404, "版本不存在")
    return await try_run(a.type, json.loads(av.config), body.input)
