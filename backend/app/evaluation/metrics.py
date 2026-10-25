"""统计口径（唯一实现）：所有报告/页面共用本模块，避免多处计算不一致。

口径定义：
- 维度均分      该维度全部有效评分（score>=0）的算术平均
- 加权总分      Σ(维度均分 × weight) / Σweight
- 通过率        全部启用维度得分均 ≥ PASS_THRESHOLD 的样本占比（执行失败样本计为不通过）
- 幻觉率        hallucination 维度得分 ≤ 2 的样本占比（分越高幻觉越少）
- P95 延迟      样本延迟的 95 分位
"""
from __future__ import annotations

import math
from statistics import mean, median

from app.core.config import settings


# ---------- 基础分布 ----------

def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
    return float(s[idx])


# ---------- 显著性检验（手写实现，免 scipy 依赖） ----------

def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全贝塔函数 I_x(a,b)（Numerical Recipes 标准实现，含对称性处理）。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    bt = math.exp(-lbeta + a * math.log(x) + b * math.log(1 - x))  # = x^a (1-x)^b / B(a,b)
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b


def t_cdf(t: float, df: int) -> float:
    """t 分布累积分布。基于恒等式：x = df/(df+t²) 时，两侧 p 值 = I_x(df/2, 1/2)。"""
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    try:
        p_two = _betai(df / 2.0, 0.5, x)
    except (ValueError, ZeroDivisionError):
        return 1.0
    return 1.0 - 0.5 * p_two if t >= 0 else 0.5 * p_two


def paired_t_test(diffs: list[float]) -> dict:
    """配对 t 检验（双侧）。"""
    n = len(diffs)
    if n < 2:
        return {"n": n, "t": None, "p": None, "method": "paired_t"}
    m = mean(diffs)
    var = sum((d - m) ** 2 for d in diffs) / (n - 1)
    if var == 0:
        return {"n": n, "t": 0.0, "p": 1.0, "method": "paired_t"}
    t = m / math.sqrt(var / n)
    p = 2 * (1 - t_cdf(abs(t), n - 1))
    return {"n": n, "t": round(t, 4), "p": round(p, 4), "method": "paired_t"}


def wilcoxon_test(diffs: list[float]) -> dict:
    """Wilcoxon 符号秩检验（正态近似），样本少时使用。"""
    nonzero = [d for d in diffs if d != 0]
    n = len(nonzero)
    if n < 5:
        return {"n": n, "w": None, "p": None, "method": "wilcoxon"}
    ranked = sorted(nonzero, key=abs)
    ranks: list[float] = []
    i = 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and abs(ranked[j + 1]) == abs(ranked[i]):
            j += 1
        avg = (i + j + 2) / 2  # 1-based 平均秩
        ranks.extend([avg] * (j - i + 1))
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, ranked) if d > 0)
    mean_w = n * (n + 1) / 4
    sd_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    if sd_w == 0:
        return {"n": n, "w": w_plus, "p": 1.0, "method": "wilcoxon"}
    z = (w_plus - mean_w) / sd_w
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"n": n, "w": w_plus, "p": round(p, 4), "method": "wilcoxon"}


# ---------- 聚合口径 ----------

def aggregate(results: list[dict], dimensions: list[dict], threshold: float | None = None) -> dict:
    """results: [{seq,status,scores:{code:float},latency_ms,token_usage:{input,output},tags,findings}]"""
    th = settings.PASS_THRESHOLD if threshold is None else threshold
    weights = {d["code"]: float(d.get("weight", 1.0)) for d in dimensions}
    total = len(results) or 1
    ok_results = [r for r in results if r.get("status") == "ok"]
    passed = 0
    hallu_cnt = 0
    hallu_total = 0
    dim_scores: dict[str, list[float]] = {c: [] for c in weights}
    latencies: list[float] = []
    tokens_in: list[float] = []
    tokens_out: list[float] = []
    for r in results:
        scores = r.get("scores", {})
        valid = {c: s for c, s in scores.items() if s is not None and s >= 0}
        if r.get("status") == "ok" and valid and all(s >= th for s in valid.values()) and len(valid) == len(weights):
            passed += 1
        if "hallucination" in valid:
            hallu_total += 1
            if valid["hallucination"] <= 2:
                hallu_cnt += 1
        for c, s in valid.items():
            if c in dim_scores:
                dim_scores[c].append(s)
        if r.get("status") == "ok":
            latencies.append(float(r.get("latency_ms", 0)))
            tu = r.get("token_usage") or {}
            if tu.get("input"):
                tokens_in.append(float(tu["input"]))
            if tu.get("output"):
                tokens_out.append(float(tu["output"]))

    dim_stats = {
        c: {
            "mean": round(mean(v), 3) if v else None,
            "median": round(median(v), 3) if v else None,
            "min": min(v) if v else None,
            "max": max(v) if v else None,
            "valid_n": len(v),
        }
        for c, v in dim_scores.items()
    }
    w_sum = sum(weights[c] for c in dim_stats if dim_stats[c]["mean"] is not None)
    weighted = (
        round(sum(dim_stats[c]["mean"] * weights[c] for c in dim_stats if dim_stats[c]["mean"] is not None) / w_sum, 3)
        if w_sum
        else None
    )
    return {
        "case_total": len(results),
        "case_ok": len(ok_results),
        "case_error": total - len(ok_results),
        "pass_rate": round(passed / total, 4),
        "hallucination_rate": round(hallu_cnt / hallu_total, 4) if hallu_total else None,
        "weighted_total": weighted,
        "dimension_stats": dim_stats,
        "latency_ms_avg": round(mean(latencies)) if latencies else None,
        "latency_ms_p95": round(percentile(latencies, 95)) if latencies else None,
        "token_input_avg": round(mean(tokens_in)) if tokens_in else None,
        "token_output_avg": round(mean(tokens_out)) if tokens_out else None,
    }


def slice_by_tag(results: list[dict], dimensions: list[dict]) -> list[dict]:
    """按 tags 中 scenario/domain/difficulty 切片的通过率与均分。"""
    out: list[dict] = []
    keys = ("scenario", "domain", "difficulty")
    groups: dict[tuple, list[dict]] = {}
    for r in results:
        tags = r.get("tags") or {}
        for k in keys:
            if tags.get(k):
                groups.setdefault((k, str(tags[k])), []).append(r)
    for (k, v), rs in sorted(groups.items()):
        agg = aggregate(rs, dimensions)
        out.append({"slice_key": k, "slice_value": v, "n": len(rs),
                    "pass_rate": agg["pass_rate"], "weighted_total": agg["weighted_total"]})
    return out


def ab_compare(
    results_a: list[dict], results_b: list[dict], dimensions: list[dict]
) -> dict:
    """A/B 配对对比：逐维度配对差值 + 胜平负 + 显著性（n>=8 用配对 t，否则 Wilcoxon）。"""
    by_seq_a = {r["seq"]: r for r in results_a}
    by_seq_b = {r["seq"]: r for r in results_b}
    common = sorted(set(by_seq_a) & set(by_seq_b))
    dim_detail = {}
    overall_diffs: list[float] = []
    win = tie = loss = 0
    for d in dimensions:
        code = d["code"]
        diffs: list[float] = []
        w = t = l = 0
        for seq in common:
            sa = by_seq_a[seq]["scores"].get(code)
            sb = by_seq_b[seq]["scores"].get(code)
            if sa is None or sb is None or sa < 0 or sb < 0:
                continue
            diffs.append(sb - sa)
            w += sb > sa
            t += sb == sa
            l += sb < sa
        if code == "hallucination" or True:
            overall_diffs.extend(diffs)
        win, tie, loss = win + w, tie + t, loss + l
        test = paired_t_test(diffs) if len(diffs) >= 8 else wilcoxon_test(diffs)
        dim_detail[code] = {
            "mean_diff": round(mean(diffs), 3) if diffs else None,
            "win": w, "tie": t, "loss": l,
            "test": test,
        }
    overall = paired_t_test(overall_diffs) if len(overall_diffs) >= 8 else wilcoxon_test(overall_diffs)
    return {
        "n_common": len(common),
        "win": win, "tie": tie, "loss": loss,  # B 相对 A 的逐维度胜负计数
        "dimensions": dim_detail,
        "overall_test": overall,
    }
