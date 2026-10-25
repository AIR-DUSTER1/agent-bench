"""评测报告生成：指标聚合（metrics.py 统一口径）→ HTML（自包含，服务端 SVG 雷达图）+ Markdown + 原始 JSON。"""
from __future__ import annotations

import json
from datetime import datetime

from jinja2 import Environment, StrictUndefined
from sqlalchemy import select

from app.attribution.engine import summarize_findings
from app.core.config import settings
from app.evaluation import metrics
from app.models import (
    Agent, AgentVersion, AttributionFinding, CaseResult, DatasetVersion,
    Dimension, EvalRun, Report,
)


def _j(text, default):
    try:
        return json.loads(text) if text else default
    except json.JSONDecodeError:
        return default


def collect(db, run_id: int) -> dict:
    run = db.get(EvalRun, run_id)
    dsv = db.get(DatasetVersion, run.dataset_version_id)
    dims = [
        {"code": d.code, "name": d.name, "weight": d.weight}
        for d in db.execute(select(Dimension).where(Dimension.enabled.is_(True))).scalars()
        if not _j(run.dimension_codes, []) or d.code in _j(run.dimension_codes, [])
    ]
    results = db.execute(select(CaseResult).where(CaseResult.run_id == run.id)).scalars().all()
    case_map = {c.id: c for c in dsv.cases}
    av_ids = _j(run.agent_version_ids, [])

    sides = []
    for av_id in av_ids:
        av = db.get(AgentVersion, av_id)
        agent = db.get(Agent, av.agent_id)
        rs = []
        for r in sorted([x for x in results if x.agent_version_id == av_id], key=lambda x: x.seq):
            case = case_map.get(r.case_id)
            rs.append({
                "seq": r.seq, "status": r.status,
                "scores": {s.dimension_code: s.score for s in r.scores},
                "score_rows": [
                    {"code": s.dimension_code, "score": s.score,
                     "rationale": s.rationale, "evidence": s.evidence, "error": s.error}
                    for s in r.scores
                ],
                "latency_ms": r.latency_ms,
                "token_usage": _j(r.token_usage, {}),
                "tags": _j(case.tags, {}) if case else {},
                "difficulty": case.difficulty if case else "",
                "input": case.input if case else "",
                "expected": case.expected_output if case else "",
                "output": r.output, "error": r.error,
                "intermediate": _j(r.intermediate, []),
                "findings": [
                    {"layer": f.layer, "issue_code": f.issue_code, "severity": f.severity,
                     "detail": f.detail, "suggestion": f.suggestion, "evidence": f.evidence}
                    for f in db.execute(
                        select(AttributionFinding).where(AttributionFinding.case_result_id == r.id)
                    ).scalars()
                ],
                "trace_id": r.trace_id,
            })
        agg = metrics.aggregate(rs, dims)
        slices = metrics.slice_by_tag(rs, dims)
        findings_flat = [f for r in rs for f in r["findings"]]
        sides.append({
            "av": {"id": av.id, "version": av.version, "agent_name": agent.name,
                   "agent_type": agent.type},
            "results": rs, "agg": agg, "slices": slices,
            "finding_modes": summarize_findings(findings_flat),
            # Jinja 不支持推导式，图表数据在 Python 侧预计算
            "radar_values": [agg["dimension_stats"][d["code"]]["mean"] for d in dims],
            "dist_values": {d["code"]: [r["scores"].get(d["code"]) for r in rs] for d in dims},
        })

    ab = None
    if run.mode == "ab" and len(sides) == 2:
        ab = metrics.ab_compare(sides[0]["results"], sides[1]["results"], dims)
        # 标签切片差异（B 相对 A 的通过率差）
        slice_diff = []
        sa = {s["slice_key"] + "|" + s["slice_value"]: s for s in sides[0]["slices"]}
        for s in sides[1]["slices"]:
            k = s["slice_key"] + "|" + s["slice_value"]
            if k in sa and sa[k]["n"] == s["n"]:
                slice_diff.append({
                    "key": s["slice_key"], "value": s["slice_value"], "n": s["n"],
                    "a_pass": sa[k]["pass_rate"], "b_pass": s["pass_rate"],
                    "delta": round(s["pass_rate"] - sa[k]["pass_rate"], 4),
                    "a_score": sa[k]["weighted_total"], "b_score": s["weighted_total"],
                })
        ab["slice_diff"] = sorted(slice_diff, key=lambda x: x["delta"], reverse=True)

    return {
        "run": run, "dataset": {"name": dsv.dataset.name, "version": dsv.version,
                                "case_count": dsv.case_count},
        "dims": dims, "sides": sides, "ab": ab,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------- SVG 图表 ----------------

def radar_svg(dim_names: list[str], values: list[float | None], color: str, size: int = 240) -> str:
    n = max(3, len(dim_names))
    cx = cy = size / 2
    r = size / 2 - 42
    import math

    pts, labels, grid = [], [], []
    for lvl in (1, 2, 3, 4, 5):
        ring = " ".join(
            f"{cx + r * lvl / 5 * math.cos(2 * math.pi * i / n - math.pi / 2):.1f},"
            f"{cy + r * lvl / 5 * math.sin(2 * math.pi * i / n - math.pi / 2):.1f}"
            for i in range(n)
        )
        grid.append(f'<polygon points="{ring}" fill="none" stroke="#e2e8f0"/>')
    poly_vals = []
    for i, name in enumerate(dim_names):
        ang = 2 * math.pi * i / n - math.pi / 2
        lx, ly = cx + (r + 26) * math.cos(ang), cy + (r + 26) * math.sin(ang)
        anchor = "middle"
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="11" fill="#475569">{name}</text>'
        )
        v = values[i] if i < len(values) and values[i] is not None else 0
        vv = max(0.0, min(5.0, float(v))) / 5
        poly_vals.append(f"{cx + r * vv * math.cos(ang):.1f},{cy + r * vv * math.sin(ang):.1f}")
        pts.append(
            f'<circle cx="{cx + r * vv * math.cos(ang):.1f}" cy="{cy + r * vv * math.sin(ang):.1f}" r="3" fill="{color}"/>'
        )
    return (
        f'<svg viewBox="0 0 {size} {size}" class="radar">{"".join(grid)}'
        f'<polygon points="{" ".join(poly_vals)}" fill="{color}33" stroke="{color}" stroke-width="2"/>'
        f'{"".join(pts)}{"".join(labels)}</svg>'
    )


def dist_bars(dim_name: str, values: list[float]) -> str:
    buckets = [0] * 6
    for v in values:
        if v is None or v < 0:
            continue
        buckets[min(5, int(v))] += 1
    mx = max(1, *buckets)
    rows = "".join(
        f'<div class="dist-row"><span class="dist-lab">{i}分</span>'
        f'<div class="dist-bar"><div class="dist-fill" style="width:{b / mx * 100:.0f}%"></div></div>'
        f'<span class="dist-n">{b}</span></div>'
        for i, b in enumerate(buckets)
    )
    return f'<div class="dist"><div class="dist-title">{dim_name}</div>{rows}</div>'


# ---------------- 模板 ----------------
# autoescape 必须开启：报告回显被测 Agent 的不可信输出（评测平台天然含对抗样本），
# 关闭即存储型 XSS（AGENTS.md §6）。图表函数返回的受信 SVG/HTML 用 Markup 显式放行。

from markupsafe import Markup  # noqa: E402

ENV = Environment(undefined=StrictUndefined, autoescape=True)
ENV.globals["radar"] = lambda *a, **k: Markup(radar_svg(*a, **k))
ENV.globals["dist"] = lambda *a, **k: Markup(dist_bars(*a, **k))

HTML_TMPL = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{{ run.name }} — 评测报告</title>
<style>
:root{--bg:#f6f8fa;--card:#fff;--ink:#1e293b;--sub:#64748b;--line:#e2e8f0;--ok:#16a34a;--bad:#dc2626;--warn:#d97706;--brand:#2563eb}
*{box-sizing:border-box}body{margin:0;font:14px/1.65 "Microsoft YaHei",system-ui,sans-serif;background:var(--bg);color:var(--ink)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:22px;margin:0 0 4px}.meta{color:var(--sub);font-size:12.5px;margin-bottom:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{color:var(--sub);font-size:12px}.card .v{font-size:24px;font-weight:700;margin-top:2px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:18px 0}
h2{font-size:16px;margin:0 0 12px;border-left:4px solid var(--brand);padding-left:8px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
th{color:var(--sub);font-weight:600;background:#f8fafc}
.tag{display:inline-block;background:#eff6ff;color:#1d4ed8;border-radius:4px;padding:0 6px;font-size:11.5px;margin:1px 2px}
.badge{display:inline-block;border-radius:4px;padding:0 6px;font-size:11.5px}
.b-high{background:#fee2e2;color:#b91c1c}.b-medium{background:#fef3c7;color:#b45309}.b-low{background:#f1f5f9;color:#475569}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.radar-row{display:flex;flex-wrap:wrap;gap:24px;align-items:center}
.dist{min-width:210px;flex:1}.dist-title{font-weight:600;font-size:13px;margin-bottom:4px}
.dist-row{display:flex;align-items:center;gap:6px;margin:2px 0}.dist-lab{width:28px;color:var(--sub);font-size:11px;text-align:right}
.dist-bar{flex:1;height:10px;background:#f1f5f9;border-radius:5px;overflow:hidden}.dist-fill{height:100%;background:var(--brand)}
.dist-n{width:26px;font-size:11px;color:var(--sub)}
details{border:1px solid var(--line);border-radius:8px;margin:8px 0;padding:6px 10px;background:#fbfdff}
summary{cursor:pointer;font-weight:600}
pre{background:#f8fafc;border:1px solid var(--line);border-radius:6px;padding:8px;white-space:pre-wrap;word-break:break-all;font-size:12px}
.pill{border-radius:999px;padding:1px 10px;font-size:12px;background:#f1f5f9}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:900px){.grid2{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1>{{ run.name }} · 评测报告</h1>
<div class="meta">数据集：{{ dataset.name }} {{ dataset.version }}（{{ dataset.case_count }} 样本） ·
模式：{{ run.mode }} · Judge：{{ run.judge_model }}/{{ run.judge_mode }} · 状态：{{ run.status }} · 生成时间：{{ generated_at }}</div>

{% for side in sides %}
<section>
<h2>{{ side.av.agent_name }}（{{ side.av.agent_type }} / {{ side.av.version }}）总体指标</h2>
<div class="cards">
  <div class="card"><div class="k">加权总分</div><div class="v">{{ side.agg.weighted_total if side.agg.weighted_total is not none else "—" }}</div></div>
  <div class="card"><div class="k">通过率</div><div class="v">{{ "%.1f"|format(side.agg.pass_rate*100) }}%</div></div>
  <div class="card"><div class="k">幻觉率</div><div class="v">{{ "%.1f"|format((side.agg.hallucination_rate or 0)*100) }}%</div></div>
  <div class="card"><div class="k">成功样本</div><div class="v">{{ side.agg.case_ok }}/{{ side.agg.case_total }}</div></div>
  <div class="card"><div class="k">平均延迟</div><div class="v">{{ side.agg.latency_ms_avg }}ms</div></div>
  <div class="card"><div class="k">P95 延迟</div><div class="v">{{ side.agg.latency_ms_p95 }}ms</div></div>
</div>
<div class="radar-row">
  {{ radar(dims|map(attribute="name")|list, side.radar_values, "#2563eb") }}
  <div style="flex:2;min-width:280px">
  {% for d in dims %}{{ dist(d.name, side.dist_values[d.code]) }}{% endfor %}
  </div>
</div>
<table><tr><th>维度</th><th>均分</th><th>中位数</th><th>最低</th><th>权重</th></tr>
{% for d in dims %}{% set st = side.agg.dimension_stats[d.code] %}<tr>
<td>{{ d.name }}</td><td><b>{{ st.mean if st.mean is not none else "—" }}</b></td>
<td>{{ st.median if st.median is not none else "—" }}</td><td>{{ st.min if st.min is not none else "—" }}</td><td>{{ d.weight }}</td></tr>{% endfor %}
</table>
<h2 style="margin-top:18px">标签切片</h2>
<table><tr><th>切片</th><th>样本数</th><th>通过率</th><th>加权分</th></tr>
{% for s in side.slices %}<tr><td>{{ s.slice_key }}={{ s.slice_value }}</td><td>{{ s.n }}</td>
<td>{{ "%.1f"|format(s.pass_rate*100) }}%</td><td>{{ s.weighted_total if s.weighted_total is not none else "—" }}</td></tr>
{% endfor %}</table>
{% if side.finding_modes %}
<h2 style="margin-top:18px">失败模式 Top（归因聚合）</h2>
<table><tr><th>层</th><th>问题</th><th>次数</th><th>建议</th></tr>
{% for f in side.finding_modes[:8] %}<tr><td>{{ f.layer }}</td><td><span class="badge b-{{ f.severity }}">{{ f.issue_code }}</span></td>
<td>{{ f.count }}</td><td style="color:var(--sub)">{{ f.suggestion }}</td></tr>{% endfor %}</table>
{% endif %}
</section>

<section>
<h2>{{ side.av.agent_name }} 样本明细</h2>
{% for r in side.results %}
<details {% if r.status != 'ok' or (r.scores.values()|list and (r.scores.values()|list|min) < 3) %}open{% endif %}>
<summary>#{{ r.seq }} · {{ r.tags.get("scenario","") }} {{ r.tags.get("domain","") }}
{% if r.status != "ok" %}<span class="badge b-high">执行失败</span>{% endif %}
{% for c, v in r.scores.items() %}<span class="pill">{{ c }} {{ v if v >= 0 else "N/A" }}</span>{% endfor %}
</summary>
<p><b>输入</b>：<pre>{{ r.input }}</pre>
{% if r.expected %}<b>期望</b>：<pre>{{ r.expected }}</pre>{% endif %}
<b>输出</b>：<pre>{{ r.output if r.output else "（空）" }}{% if r.error %}\n[error] {{ r.error }}{% endif %}</pre>
{% if r.findings %}<b>归因</b>：
{% for f in r.findings %}<p><span class="badge b-{{ f.severity }}">{{ f.layer }}/{{ f.issue_code }}</span> {{ f.detail }}<br><i style="color:var(--sub)">建议：{{ f.suggestion }}</i></p>{% endfor %}{% endif %}
{% if r.score_rows %}<b>评分依据</b>：
{% for s in r.score_rows %}{% if s.rationale or s.error %}<p>· <b>{{ s.code }}={{ s.score if s.score >= 0 else "N/A" }}</b> {{ s.rationale }}{% if s.evidence %} <i style="color:var(--sub)">证据：{{ s.evidence }}</i>{% endif %}{% if s.error %} <span class="bad">评分异常：{{ s.error }}</span>{% endif %}</p>{% endif %}{% endfor %}{% endif %}
{% if r.intermediate %}<b>执行轨迹</b>：<pre>{{ r.intermediate|tojson }}</pre>{% endif %}
</details>
{% endfor %}
</section>
{% endfor %}

{% if ab %}
<section>
<h2>A/B 对比（A={{ sides[0].av.agent_name }}/{{ sides[0].av.version }} vs B={{ sides[1].av.agent_name }}/{{ sides[1].av.version }}）</h2>
<div class="cards">
<div class="card"><div class="k">B 胜 / 平 / 负</div><div class="v">{{ ab.win }} / {{ ab.tie }} / {{ ab.loss }}</div></div>
<div class="card"><div class="k">总体检验</div><div class="v" style="font-size:16px">{{ ab.overall_test.method }}<br>p={{ ab.overall_test.p if ab.overall_test.p is not none else "—" }}</div></div>
<div class="card"><div class="k">配对样本数</div><div class="v">{{ ab.n_common }}</div></div>
</div>
<table><tr><th>维度</th><th>均分差(B−A)</th><th>B胜/平/负</th><th>检验</th><th>p 值</th><th>结论</th></tr>
{% for code, d in ab.dimensions.items() %}
{% set t = d.test %}<tr><td>{{ code }}</td><td>{{ "+" if d.mean_diff and d.mean_diff > 0 }}{{ d.mean_diff if d.mean_diff is not none else "—" }}</td>
<td>{{ d.win }}/{{ d.tie }}/{{ d.loss }}</td><td>{{ t.method }}</td><td>{{ t.p if t.p is not none else "—" }}</td>
<td>{% if t.p is not none and t.p < 0.05 %}<span class="{{ 'ok' if (d.mean_diff or 0) > 0 else 'bad' }}">差异显著</span>{% else %}不显著{% endif %}</td></tr>
{% endfor %}</table>
{% if ab.slice_diff %}
<h2 style="margin-top:18px">标签切片差异（通过率 Δ=B−A）</h2>
<table><tr><th>切片</th><th>n</th><th>A 通过率</th><th>B 通过率</th><th>Δ</th></tr>
{% for s in ab.slice_diff %}<tr><td>{{ s.key }}={{ s.value }}</td><td>{{ s.n }}</td>
<td>{{ "%.1f"|format(s.a_pass*100) }}%</td><td>{{ "%.1f"|format(s.b_pass*100) }}%</td>
<td class="{{ 'ok' if s.delta > 0 else ('bad' if s.delta < 0 else '') }}">{{ "%+.1f"|format(s.delta*100) }}%</td></tr>
{% endfor %}</table>
{% endif %}
</section>
{% endif %}
</div></body></html>"""


def _fmt_md(data: dict) -> str:
    lines = [f"# {data['run'].name} — 评测报告", ""]
    lines.append(f"- 数据集：{data['dataset']['name']} {data['dataset']['version']}（{data['dataset']['case_count']} 样本）")
    lines.append(f"- 模式：{data['run'].mode} · Judge：{data['run'].judge_model}/{data['run'].judge_mode}")
    lines.append(f"- 生成时间：{data['generated_at']}")
    for side in data["sides"]:
        a = side["agg"]
        lines += ["", f"## {side['av']['agent_name']}（{side['av']['agent_type']}/{side['av']['version']}）", "",
                  f"- 加权总分 **{a['weighted_total']}** · 通过率 **{a['pass_rate']*100:.1f}%** · 幻觉率 **{(a['hallucination_rate'] or 0)*100:.1f}%**",
                  f"- 成功样本 {a['case_ok']}/{a['case_total']} · 平均延迟 {a['latency_ms_avg']}ms · P95 {a['latency_ms_p95']}ms", "",
                  "| 维度 | 均分 | 中位数 | 最低 |", "|---|---|---|---|"]
        for d in data["dims"]:
            st = a["dimension_stats"][d["code"]]
            lines.append(f"| {d['name']} | {st['mean']} | {st['median']} | {st['min']} |")
        if side["finding_modes"]:
            lines += ["", "### 失败模式 Top", "| 层 | 问题 | 次数 |", "|---|---|---|"]
            for f in side["finding_modes"][:8]:
                lines.append(f"| {f['layer']} | {f['issue_code']} | {f['count']} |")
    if data["ab"]:
        ab = data["ab"]
        lines += ["", "## A/B 对比", f"- B 胜/平/负：{ab['win']}/{ab['tie']}/{ab['loss']}",
                  f"- 总体检验：{ab['overall_test']}", "",
                  "| 维度 | 均分差(B−A) | 胜/平/负 | p 值 |", "|---|---|---|---|"]
        for code, d in ab["dimensions"].items():
            lines.append(f"| {code} | {d['mean_diff']} | {d['win']}/{d['tie']}/{d['loss']} | {d['test']['p']} |")
    return "\n".join(lines)


def generate_reports(db, run_id: int) -> dict:
    data = collect(db, run_id)
    run = data["run"]
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"run_{run_id}_{run.name}")
    base = safe[:80].strip("_")

    html = ENV.from_string(HTML_TMPL).render(**data)
    html_path = settings.report_dir / f"{base}.html"
    html_path.write_text(html, encoding="utf-8")

    md_path = settings.report_dir / f"{base}.md"
    md_path.write_text(_fmt_md(data), encoding="utf-8")

    summary = {
        "sides": [
            {"agent": s["av"]["agent_name"], "version": s["av"]["version"], "agg": s["agg"],
             "finding_modes": s["finding_modes"]}
            for s in data["sides"]
        ],
        "ab": _ab_serializable(data["ab"]),
    }
    json_path = settings.report_dir / f"{base}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    db.add(Report(run_id=run_id, kind="ab_compare" if run.mode == "ab" else "summary",
                  summary=json.dumps(summary, ensure_ascii=False, default=str),
                  html_path=str(html_path), md_path=str(md_path)))
    db.commit()
    return {"html": str(html_path), "md": str(md_path), "json": str(json_path), "summary": summary}


def _ab_serializable(ab):
    if not ab:
        return None
    return {"win": ab["win"], "tie": ab["tie"], "loss": ab["loss"],
            "overall_test": ab["overall_test"],
            "dimensions": ab["dimensions"], "n_common": ab["n_common"]}
