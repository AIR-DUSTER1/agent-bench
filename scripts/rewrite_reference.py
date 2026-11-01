"""把"轨迹式参考答案"改写成验收要点（PLAN-V3 R2）。

背景：HF 数据集的 expected_output 是 GLM-5.2 带工具多轮执行的轨迹（或合成工具结果），
纯推理 Agent 的单轮作答与它不可比。本脚本用 Judge LLM 离线把每条参考答案压缩成
3-6 条客观可判分的验收要点，并判定 tool_dependent（合成工具结果类样本剔除，决策点 3）。

用法（backend/ 下）：
    python ../scripts/rewrite_reference.py --dataset "HF grug-think 抽样" [--dataset ...] \
        [--api http://127.0.0.1:8000] [--publish]

只改草稿并更新 meta（reference_style=key_points）；--publish 时自动发布 v2，否则人工抽检后手动发布。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

# 本机直连后端，不走系统代理（代理环境变量会劫持 127.0.0.1 导致空响应）
client = httpx.Client(trust_env=False, timeout=120)  # noqa: E402

from app.evaluation.judge import _extract_json  # noqa: E402
from app.integrations.llm import build_judge_llm  # noqa: E402

PROMPT = """你是评测数据加工员。把「原始参考答案」改写为 3-6 条客观可判分的验收要点。

要求：
- 每条是一个可独立核对的事实性要求（数值、结论、必须包含的要素、格式约束）
- 禁止相对表述（如"与参考答案一致"、"涵盖上述内容"）
- 用与任务相同的语言书写
- 另判断 tool_dependent：该参考结果是否必须真实执行外部工具/访问实时环境才能得到
  （例如"生成一个随机数"的结果、"当前天气"），纯推理可得的结论不算

只输出一个 JSON 对象：{{"key_points": ["...", ...], "tool_dependent": true/false, "reason": "一句话"}}

<<< 用户输入 >>>
{input}
<<<

<<< 原始参考答案 >>>
{expected}
<<<"""


def _get(path: str) -> dict:  # noqa: D401  依赖 main() 注入的全局 api 前缀
    """GET + 空响应重试：新进程首请求偶发空 body（诊断用打印保留）。"""
    r = None
    for attempt in range(3):
        r = client.get(g_api + "/api" + path)
        if r.status_code == 200 and r.content:
            try:
                return r.json()
            except ValueError:
                print(f"  [诊断] {path} 非 JSON：enc={r.headers.get('content-encoding')} "
                      f"ct={r.headers.get('content-type')} head={r.content[:80]!r}")
                raise
        print(f"  [重试 {attempt + 1}] GET {path} -> {r.status_code} len={len(r.content)}")
        time.sleep(2)
    raise SystemExit(f"GET {path} 持续失败: {r.status_code} body={r.text[:200]!r}")


def rewrite_one(llm, case: dict) -> dict | None:
    """单条改写；解析失败返回 None（调用方保留原样并计数）。"""
    msg = PROMPT.format(input=case["input"][:3000], expected=case["expected_output"][:2000])
    try:
        resp = llm.invoke([("user", msg)])
        data = _extract_json(resp.content if isinstance(resp.content, str) else str(resp.content))
        points = data.get("key_points")
        if not isinstance(points, list) or not points:
            return None
        return {
            "key_points": [str(p)[:300] for p in points][:6],
            "tool_dependent": bool(data.get("tool_dependent")),
            "reason": str(data.get("reason", ""))[:200],
        }
    except Exception as e:  # noqa: BLE001  单条失败不中断整批
        print(f"  改写失败（保留原样）：{type(e).__name__}: {str(e)[:120]}")
        return None


def main() -> None:
    global g_api
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", action="append", required=True, help="数据集名称，可多次")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--publish", action="store_true", help="改写完成后自动发布 v2")
    args = ap.parse_args()

    llm = build_judge_llm()
    g_api = args.api.rstrip("/")

    for name in args.dataset:
        ds = next((d for d in _get("/datasets") if d["name"] == name), None)
        if not ds:
            print(f"[{name}] 数据集不存在，跳过")
            continue
        detail = _get(f"/datasets/{ds['id']}")
        draft = detail["draft"]
        print(f"[{name}] 草稿 {len(draft['cases'])} 条")
        kept, dropped, failed = 0, 0, 0
        for case in draft["cases"]:
            out = rewrite_one(llm, case)
            if out is None:
                failed += 1
                continue
            if out["tool_dependent"]:
                client.delete(f"{g_api}/api/datasets/{ds['id']}/cases/{case['id']}")
                dropped += 1
                print(f"  #{case['seq']} 剔除（工具强依赖）：{out['reason'][:60]}")
                continue
            new_expected = "验收要点（逐条判分）：\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(out["key_points"], 1))
            client.put(f"{g_api}/api/datasets/{ds['id']}/cases/{case['id']}", json={
                "expected_output": new_expected,
                "meta": {"reference_style": "key_points", "rewritten": True,
                         "rewrite_reason": out["reason"]},
            })
            kept += 1
            time.sleep(0.5)
        print(f"[{name}] 完成：改写 {kept} / 剔除 {dropped} / 失败保留原样 {failed}")
        if args.publish:
            pub = client.post(f"{g_api}/api/datasets/{ds['id']}/publish", json={"note": "参考答案改写为验收要点 v2"})
            print(f"[{name}] 发布: {pub.json()}")


if __name__ == "__main__":
    main()
