"""一键引导：导入内置评测集并发布、注册内置 Agent 与外部被测项目。

幂等：同名数据集/Agent 已存在则跳过。用法：
    cd backend && python ../scripts/bootstrap.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.governance.quality import check_dataset, summarize  # noqa: E402
from app.models import (  # noqa: E402
    Agent, AgentVersion, Dataset, DatasetVersion, EvalCase, TagDict,
)

SEED = ROOT / "seed"

DATASETS = [
    {"file": "prompt_reasoning.json", "name": "Prompt 推理评测集",
     "description": "纯推理/写作/格式遵循/注入攻防", "target_types": "prompt,external_http,external_cli"},
    {"file": "rag_kb.json", "name": "RAG 知识库评测集",
     "description": "基于企业知识库的检索问答与幻觉陷阱", "target_types": "rag"},
    {"file": "tool_nl2sql.json", "name": "Tool 工具调用评测集",
     "description": "NL2SQL/计算器/知识检索/危险操作防御", "target_types": "tool"},
    {"file": "general_agent.json", "name": "通用能力评测集",
     "description": "外部 Agent 通用能力（推理/格式/安全/编码）", "target_types": "prompt,external_http,external_cli"},
]

AGENTS = [
    {"name": "Prompt-Agent-v1", "type": "prompt",
     "description": "内置纯推理 Agent（LCEL 直链）",
     "config": {"model": None}},
    {"name": "RAG-Agent-v1", "type": "rag",
     "description": "内置 RAG Agent（BM25 检索 + 引用生成）",
     "config": {"top_k": 3}},
    {"name": "Tool-Agent-v1", "type": "tool",
     "description": "内置 Tool Agent（sql_query/calculator/knowledge_search）",
     "config": {}},
    {"name": "learn-agent", "type": "external_http",
     "description": "被测项目：LangGraph Agent 工作台（E:\\study\\work\\learn-agent，Web API）",
     "config": {
         "base_url": "http://127.0.0.1:3000",
         "protocol": "learn_agent_sse",
         "session_body": {"kind": "agent"},
     }},
    {"name": "deepseek-harness", "type": "external_cli",
     "description": "被测项目：DeepSeek Harness（dsh --profile headless 一次性调用）",
     "config": {
         "argv": ["dsh", "--profile", "headless", "{input}"],
         "timeout": 240,
     }},
]


def _valid_tags(db) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for t in db.query(TagDict).filter_by(enabled=True).all():
        out.setdefault(t.category, set()).add(t.value)
    return out


def seed_datasets(db) -> None:
    for spec in DATASETS:
        if db.query(Dataset).filter_by(name=spec["name"]).first():
            print(f"  数据集已存在，跳过: {spec['name']}")
            continue
        cases = json.loads((SEED / "datasets" / spec["file"]).read_text(encoding="utf-8"))
        ds = Dataset(name=spec["name"], description=spec["description"],
                     target_types=spec["target_types"])
        db.add(ds)
        db.flush()
        draft = DatasetVersion(dataset_id=ds.id, version="draft")
        db.add(draft)
        db.flush()
        for i, c in enumerate(cases, 1):
            db.add(EvalCase(
                dataset_version_id=draft.id, seq=i, input=c["input"],
                expected_output=c.get("expected_output", ""),
                reference_context=c.get("reference_context", ""),
                tools_spec=json.dumps(c.get("tools_spec", {}), ensure_ascii=False),
                difficulty=c.get("difficulty", "medium"),
                tags=json.dumps(c.get("tags", {}), ensure_ascii=False),
            ))
        # 质检并发布 v1
        summary = summarize(check_dataset(
            cases, valid_tags=_valid_tags(db), target_types=spec["target_types"]))
        if summary["blockers"] > 0:
            print(f"  ✗ {spec['name']} 存在阻断问题: {summary['by_rule']}")
            db.rollback()
            continue
        snap = DatasetVersion(
            dataset_id=ds.id, version="v1", case_count=len(cases),
            quality_summary=json.dumps({"warnings": summary["warnings"]}, ensure_ascii=False),
        )
        db.add(snap)
        db.flush()
        for i, c in enumerate(cases, 1):
            db.add(EvalCase(
                dataset_version_id=snap.id, seq=i, input=c["input"],
                expected_output=c.get("expected_output", ""),
                reference_context=c.get("reference_context", ""),
                tools_spec=json.dumps(c.get("tools_spec", {}), ensure_ascii=False),
                difficulty=c.get("difficulty", "medium"),
                tags=json.dumps(c.get("tags", {}), ensure_ascii=False),
            ))
        db.commit()
        print(f"  ✓ 数据集「{spec['name']}」导入并发布 v1（{len(cases)} 样本，警告 {summary['warnings']}）")


def seed_agents(db) -> None:
    for spec in AGENTS:
        if db.query(Agent).filter_by(name=spec["name"]).first():
            print(f"  Agent 已存在，跳过: {spec['name']}")
            continue
        a = Agent(name=spec["name"], description=spec["description"], type=spec["type"])
        db.add(a)
        db.flush()
        config = dict(spec["config"])
        config.pop("model", None)  # 内置 Agent 的模型回落 .env 全局配置
        db.add(AgentVersion(agent_id=a.id, version="v1",
                            config=json.dumps(config, ensure_ascii=False),
                            note="bootstrap 自动注册"))
        db.commit()
        print(f"  ✓ Agent「{spec['name']}」（{spec['type']}）注册，版本 v1")


def main() -> None:
    print("初始化数据库与内置维度/标签…")
    init_db()
    with SessionLocal() as db:
        print("导入评测集…")
        seed_datasets(db)
        print("注册 Agent…")
        seed_agents(db)
    print("完成。")


if __name__ == "__main__":
    main()
