"""数据质量校验：重复（精确+近似）/ 缺失 / 异常检测。

issue 级别：blocker（须修复才能发布）| warning（提示）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_INPUT_LEN = 8000
MIN_INPUT_LEN = 2
GARBLED_RATIO = 0.15  # 不可打印/替换字符占比阈值
NEAR_DUP_JACCARD = 0.85


@dataclass
class Issue:
    level: str   # blocker | warning
    rule: str
    seq: int | None = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {"level": self.level, "rule": self.rule, "seq": self.seq, "detail": self.detail}


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _bigrams(text: str) -> set[str]:
    t = _norm(text)
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _garbled_ratio(text: str) -> float:
    if not text:
        return 0.0
    bad = sum(1 for c in text if (ord(c) < 32 and c not in "\n\t") or ord(c) == 0xFFFD)
    return bad / len(text)


def validate_case(
    case: dict, seq: int, *, valid_tags: dict[str, set[str]], target_types: str = ""
) -> list[Issue]:
    issues: list[Issue] = []
    inp = (case.get("input") or "").strip()

    # ---- 缺失检测（blocker）----
    if not inp:
        issues.append(Issue("blocker", "missing_input", seq, "input 为空"))
    if not (case.get("expected_output") or "").strip():
        issues.append(Issue("blocker", "missing_expected", seq, "expected_output 为空（评分锚点缺失）"))
    # 场景化必填：RAG 类数据集缺参考上下文
    types = [t.strip() for t in target_types.split(",") if t.strip()]
    if "rag" in types and not (case.get("reference_context") or "").strip():
        issues.append(Issue("blocker", "missing_rag_context", seq, "RAG 数据集样本缺少 reference_context"))
    if "tool" in types and not (case.get("tools_spec") or {}).get("expected_tool"):
        issues.append(Issue("warning", "missing_tool_spec", seq, "tool 数据集样本未声明 expected_tool（Tool 层归因将受限）"))

    # ---- 异常检测 ----
    if inp and len(inp) > MAX_INPUT_LEN:
        issues.append(Issue("warning", "too_long", seq, f"input 长度 {len(inp)} 超过 {MAX_INPUT_LEN}"))
    if inp and len(inp) < MIN_INPUT_LEN:
        issues.append(Issue("blocker", "too_short", seq, f"input 过短：{inp!r}"))
    if _garbled_ratio(inp) > GARBLED_RATIO:
        issues.append(Issue("blocker", "garbled", seq, "input 疑似乱码（不可打印字符比例过高）"))

    # ---- 标签合法性 ----
    tags = case.get("tags") or {}
    for cat, values in valid_tags.items():
        v = tags.get(cat)
        if v and values and v not in values:
            issues.append(Issue("blocker", "invalid_tag", seq, f"标签 {cat}={v!r} 不在字典中"))
    diff = (case.get("difficulty") or "medium").lower()
    if diff not in ("easy", "medium", "hard"):
        issues.append(Issue("blocker", "invalid_difficulty", seq, f"difficulty={diff!r} 非法"))
    return issues


def check_dataset(cases: list[dict], *, valid_tags: dict[str, set[str]], target_types: str = "") -> list[Issue]:
    """整库检查：逐条校验 + 精确/近似去重 + 分布告警。"""
    issues: list[Issue] = []
    seen_hash: dict[str, int] = {}
    bigram_sets: list[set[str]] = []
    seqs: list[int] = []

    for i, case in enumerate(cases):
        seq = case.get("seq", i + 1)
        seqs.append(seq)
        issues.extend(validate_case(case, seq, valid_tags=valid_tags, target_types=target_types))
        # 精确重复
        h = hashlib.md5(_norm(case.get("input", "")).encode("utf-8")).hexdigest()
        if h in seen_hash:
            issues.append(Issue("blocker", "dup_exact", seq, f"与样本 #{seen_hash[h]} 输入完全相同"))
        else:
            seen_hash[h] = seq
        bigram_sets.append(_bigrams(case.get("input", "")))
    # 近似重复（字符二元组 Jaccard，O(n²)，评测集规模下可接受）
    for i in range(len(bigram_sets)):
        for j in range(i + 1, len(bigram_sets)):
            a, b = bigram_sets[i], bigram_sets[j]
            if not a or not b:
                continue
            j_ = len(a & b) / len(a | b)
            if j_ >= NEAR_DUP_JACCARD:
                issues.append(Issue("warning", "dup_near", seqs[j],
                                    f"与样本 #{seqs[i]} 近似重复（Jaccard={j_:.2f}）"))
    # 难度分布倾斜（仅告警）
    if cases:
        hard = sum(1 for c in cases if (c.get("difficulty") or "").lower() == "hard")
        if hard / len(cases) > 0.7:
            issues.append(Issue("warning", "skewed_difficulty", None,
                                f"hard 占比 {hard}/{len(cases)}，建议补充 easy/medium 样本"))
    return issues


def summarize(issues: list[Issue]) -> dict:
    blockers = sum(1 for i in issues if i.level == "blocker")
    warnings = sum(1 for i in issues if i.level == "warning")
    by_rule: dict[str, int] = {}
    for i in issues:
        by_rule[i.rule] = by_rule.get(i.rule, 0) + 1
    return {"blockers": blockers, "warnings": warnings, "by_rule": by_rule,
            "issues": [i.as_dict() for i in issues]}
