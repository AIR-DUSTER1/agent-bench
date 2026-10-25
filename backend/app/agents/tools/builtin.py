"""Tool Agent 内置工具集（演示数据库只读 SQL / 计算器 / 知识检索）。

安全约束（AGENTS.md §4/§6）：
- sql_query 只读：先剔除字符串字面量再做写操作关键字词边界检测（防 %create% 误伤、防子串绕过）
- calculator 用 AST 白名单求值器，绝不使用 eval()——输入是模型生成的不可信内容
"""
from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

from langchain_core.tools import tool

# builtin.py 位于 backend/app/agents/tools/ → parents[4] = 仓库根
ROOT = Path(__file__).resolve().parents[4]
DEMO_DB = ROOT / "seed" / "demo.db"
KB_DIR = ROOT / "seed" / "kb"

FORBIDDEN_SQL = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "load_extension",
)


@tool
def sql_query(sql: str) -> str:
    """对演示业务数据库执行只读 SQL 查询并返回结果。库表：products(产品)、sales(销售)、employees(员工)。参数 sql：合法的 SELECT 语句。"""
    lowered = sql.strip().lower()
    if not lowered.startswith(("select", "with")):
        return "ERROR: 只允许 SELECT/WITH 查询"
    # 先剔除字符串字面量再查写操作关键字（词边界），避免 '%update%' 之类误伤，也防子串拼接绕过
    no_literals = re.sub(r"'[^']*'", "''", lowered)
    if any(re.search(rf"\b{k}\b", no_literals) for k in FORBIDDEN_SQL):
        return "ERROR: 检测到写操作/危险关键字，已拒绝（只读工具）"
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


# ---------- 安全算术求值器（AST 白名单，替代 eval） ----------

_ALLOWED_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}


def safe_arith(expression: str) -> float:
    """对只含数字与 + - * / % ** 和括号的表达式求值。

    防护：名称/属性/调用等 AST 节点一律拒绝（无内置逃逸）；
    指数运算限制底数与指数幅度，阻断 9**9**9 这类指数塔造成的内存耗尽。
    """
    if not expression or len(expression) > 200:
        raise ValueError("表达式为空或过长")
    if re.search(r"[^0-9+\-*/%(). ]", expression):
        raise ValueError("非法字符")
    tree = ast.parse(expression, mode="eval")

    def _eval(node: ast.AST, depth: int = 0) -> float:
        if depth > 64:
            raise ValueError("表达式嵌套过深")
        if isinstance(node, ast.Expression):
            return _eval(node.body, depth)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError("仅支持数字常量")
        if isinstance(node, ast.UnaryOp):
            v = _eval(node.operand, depth + 1)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return +v
            raise ValueError("非法一元运算")
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
            left = _eval(node.left, depth + 1)
            right = _eval(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and (abs(left) > 1e4 or not (-128 <= right <= 128)):
                raise ValueError("指数过大（防资源耗尽）")
            try:
                return _ALLOWED_OPS[type(node.op)](left, right)
            except ZeroDivisionError:
                raise ValueError("除数为零") from None
        raise ValueError("不支持的表达式节点")

    return _eval(tree)


@tool
def calculator(expression: str) -> str:
    """计算数学表达式（支持 + - * / ** % 和括号）。参数 expression：如 "(12+7)*3"。"""
    try:
        return str(safe_arith(expression))
    except (ValueError, SyntaxError) as e:
        return f"ERROR: {e}"


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
