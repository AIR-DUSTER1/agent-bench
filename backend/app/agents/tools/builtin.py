"""Tool Agent 内置工具集（演示数据库只读 SQL / 计算器 / 知识检索）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from langchain_core.tools import tool

# builtin.py 位于 backend/app/agents/tools/ → parents[4] = 仓库根
ROOT = Path(__file__).resolve().parents[4]
DEMO_DB = ROOT / "seed" / "demo.db"
KB_DIR = ROOT / "seed" / "kb"

FORBIDDEN_SQL = ("insert", "update", "delete", "drop", "alter", "create", "replace", "attach", "pragma")


@tool
def sql_query(sql: str) -> str:
    """对演示业务数据库执行只读 SQL 查询并返回结果。库表：products(产品)、sales(销售)、employees(员工)。参数 sql：合法的 SELECT 语句。"""
    lowered = sql.strip().lower()
    if not lowered.startswith(("select", "with")):
        return "ERROR: 只允许 SELECT/WITH 查询"
    if any(k in lowered for k in FORBIDDEN_SQL):
        return "ERROR: 检测到写操作关键字，已拒绝（只读工具）"
    if not DEMO_DB.exists():
        return "ERROR: 演示数据库未初始化"
    try:
        conn = sqlite3.connect(DEMO_DB)
        try:
            cur = conn.execute(sql)
            rows = cur.fetchmany(20)
            cols = [d[0] for d in cur.description] if cur.description else []
            return str({"columns": cols, "rows": [list(r) for r in rows], "rowcount": len(rows)})
        finally:
            conn.close()
    except sqlite3.Error as e:
        return f"ERROR: SQL 执行失败: {e}"


@tool
def calculator(expression: str) -> str:
    """计算数学表达式（支持 + - * / ** % 和括号）。参数 expression：如 "(12+7)*3"。"""
    if not expression or any(c not in "0123456789+-*/%(). " for c in expression):
        return "ERROR: 非法表达式"
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307 已白名单校验
    except ZeroDivisionError:
        return "ERROR: 除数为零"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: 计算失败: {e}"


@tool
def knowledge_search(keyword: str) -> str:
    """在企业知识库中按关键词检索资料标题与摘要。参数 keyword：检索关键词。"""
    from app.agents.retrieval import load_kb

    store = load_kb(KB_DIR)
    hits = store.search(keyword, k=3)
    if not hits:
        return "（未检索到资料）"
    return "\n".join(f"- {h['title']}：{h['text'][:120]}…" for h, _ in hits)


BUILTIN_TOOLS = {"sql_query": sql_query, "calculator": calculator, "knowledge_search": knowledge_search}
