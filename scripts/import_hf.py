"""HF 数据集 → agent-bench 评测集：一条命令完成抽样、转换、导入、发布。

用法（在 backend/ 下，用后端 venv 的 python 运行）：
    python ../scripts/import_hf.py <hf_id> --name "数据集名" [--limit 10] \
        [--template auto] [--tags '{"domain":"编码"}'] [--api http://127.0.0.1:8000] [--no-publish]

流程：datasets-server 分散抽样（input 去重）→ 模板抽取用例 → 标签映射 →
     创建/复用数据集 → 预检（有阻断则剔除问题样本重试一次）→ 确认导入 → 发布。
纯函数（pick_template/extract_case/dedupe_cases/map_tag_value）有离线单测。
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request

HF_DS = "https://datasets-server.huggingface.co"

# HF 侧常见取值 → 本系统受控标签值的映射（标签字典见 governance/tags.py）
TAG_VALUE_MAP = {"编程": "编码", "code": "编码", "coding": "编码", "program": "编码"}
DEFAULT_TAGS = {"domain": "编码", "scenario": "推理", "risk": "low"}
QA_TAGS = {"domain": "通用", "scenario": "单轮问答", "risk": "low"}
MAX_INPUT_CHARS = 4000
MAX_EXPECTED_CHARS = 1500


def _get_json(url: str, timeout: int = 60):
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read().decode())


def _clean(text) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _cap(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "…（截断）"


def pick_template(features: dict) -> str:
    """按 HF 数据集字段自动选抽取模板：prompt+messages=会话型，messages=对话型。"""
    if "prompt" in features and "messages" in features:
        return "prompt_messages"
    if "messages" in features:
        return "messages"
    raise SystemExit(f"无法识别的数据集字段：{list(features)}（用 --template 显式指定或自定义映射）")


def extract_case(row: dict, template: str) -> dict | None:
    """一行 HF 数据 → agent-bench 用例；不满足质量条件（空/过短/未完成轨迹）返回 None。"""
    if template == "prompt_messages":
        inp = _clean(row.get("prompt"))
        ans = ""
        for m in reversed(row.get("messages") or []):
            if m.get("role") == "assistant":
                ans = _clean(m.get("content") or "")
                if ans:
                    break
    else:  # messages：取最后一条 user 与最后一条非工具调用的 assistant 收尾
        msgs = row.get("messages") or []
        users = [m for m in msgs if m.get("role") == "user" and _clean(m.get("content"))]
        assistants = [m for m in msgs if m.get("role") == "assistant"]
        if not users or not assistants:
            return None
        last = assistants[-1]
        if last.get("tool_calls"):
            return None  # 轨迹以工具调用收尾 = 未完成
        inp = _clean(users[-1]["content"])
        ans = _clean(last.get("content"))
    if not inp or not ans or len(ans) < 30:
        return None
    return {"input": _cap(inp, MAX_INPUT_CHARS), "expected_output": _cap(ans, MAX_EXPECTED_CHARS)}


def dedupe_cases(cases: list[dict]) -> list[dict]:
    """按 input 前缀去重（HF 轨迹集常见同轨迹多步骤拆行，user 消息完全相同）。"""
    seen: set[str] = set()
    out = []
    for c in cases:
        key = c["input"][:200]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def map_tag_value(value: str) -> str:
    return TAG_VALUE_MAP.get(value, value)


def sample_rows(hf_id: str, limit: int, fetch=None) -> list[dict]:
    """分散抽样：全库 5 个等距偏移各取一页，避免只取开头（开头常是同轨迹连续行）。"""
    fetch = fetch or _get_json
    q = urllib.parse.quote(hf_id, safe="")
    size = fetch(f"{HF_DS}/info?dataset={q}")["dataset_info"]["default"]["splits"].get("train", {}).get("num_examples", 0)
    per_page = max(limit, 25)
    offsets = [size * i // 5 for i in range(5)] if size > per_page * 5 else [0]
    rows: list[dict] = []
    for off in offsets:
        d = fetch(f"{HF_DS}/rows?dataset={q}&config=default&split=train&offset={off}&length={per_page}")
        rows.extend(r["row"] for r in d.get("rows", []))
        if len(rows) >= limit * 4:  # 转换后有过滤损耗，多采 4 倍候选
            break
    return rows


def to_cases(rows: list[dict], template: str, limit: int, tags: dict | None, hf_id: str) -> list[dict]:
    base_tags = dict(tags or (QA_TAGS if template == "messages" else DEFAULT_TAGS))
    cases = []
    for row in rows:
        case = extract_case(row, template)
        if not case or len(cases) >= limit:
            continue
        case["tags"] = {k: map_tag_value(v) for k, v in base_tags.items()}
        case["meta"] = {"source": f"hf:{hf_id}", "row_fields": {
            k: row[k] for k in ("lang", "category", "domain", "task", "reasoning_effort", "teacher_model") if k in row}}
        cases.append(case)
    return dedupe_cases(cases)


def api(api_base: str, path: str, body=None, method: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api_base + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
    except urllib.error.HTTPError as e:
        return {"__error__": e.code, "body": json.loads(e.read().decode())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("hf_id", help="HuggingFace 数据集 ID，如 ProCreations/grug-think")
    ap.add_argument("--name", required=True, help="本系统中的数据集名称（已存在则复用）")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--template", default="auto", choices=["auto", "messages", "prompt_messages"])
    ap.add_argument("--tags", default=None, help='JSON，覆盖默认标签，如 \'{"domain":"编码"}\'')
    ap.add_argument("--description", default="")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args()

    features = _get_json(f"{HF_DS}/info?dataset={urllib.parse.quote(args.hf_id, safe='')}")
    feats = features["dataset_info"]["default"]["features"]
    template = args.template if args.template != "auto" else pick_template(feats)
    print(f"模板: {template}")

    rows = sample_rows(args.hf_id, args.limit)
    cases = to_cases(rows, template, args.limit, json.loads(args.tags) if args.tags else None, args.hf_id)
    print(f"抽样转换: {len(cases)} 条（候选 {len(rows)} 行）")
    if not cases:
        raise SystemExit("没有可用样本")

    dss = api(args.api, "/datasets")
    ds = next((d for d in dss if d["name"] == args.name), None)
    if not ds:
        ds = api(args.api, "/datasets", {"name": args.name, "target_types": "prompt",
                                         "description": args.description or f"来自 HuggingFace {args.hf_id} 抽样"})
    ds_id = ds["id"]

    # 预检 → 有阻断剔除问题 seq 重试一次（质检口径不绕过）
    pre = api(args.api, f"/datasets/{ds_id}/import", {"cases": cases, "confirm": False})
    if pre.get("quality", {}).get("blockers", 0) > 0:
        bad = {i["seq"] for i in pre["quality"]["issues"] if i["level"] == "blocker" and i.get("seq")}
        print(f"预检阻断 {len(bad)} 条，剔除后重试: {sorted(bad)}")
        cases = [c for i, c in enumerate(cases, start=1) if i not in bad]
    r = api(args.api, f"/datasets/{ds_id}/import", {"cases": cases, "confirm": True})
    if "__error__" in r:
        raise SystemExit(f"导入失败: {json.dumps(r['body'], ensure_ascii=False)[:300]}")
    print(f"导入: {r['imported']} 条，阻断 {r['quality']['blockers']}，提醒 {r['quality']['warnings']}")

    if args.no_publish:
        return
    pub = api(args.api, f"/datasets/{ds_id}/publish", {"note": f"import_hf {args.hf_id}"})
    if "__error__" in pub:
        raise SystemExit(f"发布失败: {json.dumps(pub['body'], ensure_ascii=False)[:300]}")
    print(f"发布: {pub['version']} (version_id={pub['id']}, {pub['case_count']} 样本)")


if __name__ == "__main__":
    main()
