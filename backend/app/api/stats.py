"""全局统计路由：token 消耗按 run / Agent / 日期三视图聚合（口径经 metrics.sum_usage）。"""
from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.evaluation.metrics import sum_usage
from app.models import Agent, AgentVersion, CaseResult, EvalRun

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/tokens")
def token_stats(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(CaseResult, EvalRun).join(EvalRun, CaseResult.run_id == EvalRun.id)
    ).all()
    av_map = {av.id: av for av in db.execute(select(AgentVersion)).scalars()}
    agent_map = {a.id: a for a in db.execute(select(Agent)).scalars()}

    by_run: dict[int, dict] = {}
    by_agent_raw: dict[str, dict] = defaultdict(lambda: {"agent": [], "judge": []})
    by_date_raw: dict[str, dict] = defaultdict(lambda: {"agent": [], "judge": []})
    all_agent: list[dict] = []
    all_judge: list[dict] = []

    for res, run in rows:
        agent_u = json.loads(res.token_usage or "{}")
        judge_u = json.loads(res.judge_usage or "{}")
        all_agent.append(agent_u)
        all_judge.append(judge_u)

        e = by_run.setdefault(run.id, {
            "run_id": run.id, "name": run.name, "status": run.status,
            "created_at": run.created_at.isoformat(), "agent": [], "judge": [],
        })
        e["agent"].append(agent_u)
        e["judge"].append(judge_u)

        av = av_map.get(res.agent_version_id)
        name = "?"
        if av:
            a = agent_map.get(av.agent_id)
            name = f"{a.name}/{av.version}" if a else f"?/{av.version}"
        by_agent_raw[name]["agent"].append(agent_u)
        by_agent_raw[name]["judge"].append(judge_u)

        day = run.created_at.date().isoformat()
        by_date_raw[day]["agent"].append(agent_u)
        by_date_raw[day]["judge"].append(judge_u)

    def _view(raw: dict, key_field: str, extra: dict | None = None) -> list[dict]:
        out = []
        for key, u in sorted(raw.items()):
            item = {key_field: key, "agent": sum_usage(u["agent"]), "judge": sum_usage(u["judge"])}
            if extra:
                item.update(extra(key))
            out.append(item)
        return out

    return {
        "total": {"agent": sum_usage(all_agent), "judge": sum_usage(all_judge)},
        "by_run": [
            {"run_id": e["run_id"], "name": e["name"], "status": e["status"],
             "created_at": e["created_at"],
             "agent": sum_usage(e["agent"]), "judge": sum_usage(e["judge"])}
            for e in sorted(by_run.values(), key=lambda x: x["run_id"], reverse=True)
        ],
        "by_agent": _view(by_agent_raw, "key"),
        "by_date": _view(by_date_raw, "key"),
    }
