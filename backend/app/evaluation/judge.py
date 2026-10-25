"""LLM-as-Judge 多维度评分器。

- single_call 模式：一次调用评全部维度（默认，省 token）
- per_dimension 模式：逐维度独立调用（更聚焦）
- 结构化 JSON 输出 + 解析重试；每条评分带 rationale/evidence 落库可追溯
"""
from __future__ import annotations

import json
import re

from app.core.config import settings
from app.evaluation.rubrics import RUBRIC_SCALE
from app.integrations.llm import build_judge_llm
from app.integrations.tracing import record_trace

SYSTEM_TMPL = """你是严格、公正的 AI 评测专家（LLM-as-Judge）。请对下方「待评回答」按给定的评测维度逐维打分。

{scale}

各维度评分标准（Rubric）：
{rubrics}

评分输出要求：只输出一个 JSON 对象，不要任何其他文字、不要 Markdown 代码块。结构：
{{
  "scores": {{
{schema}
  }}
}}
每个维度对象包含：score（0-5 数字）、rationale（30-80字评分理由）、evidence（引用待评回答或参考答案中的原文片段）。"""

DIM_SCHEMA = '    "{code}": {{"score": <0-5>, "rationale": "...", "evidence": "..."}}'

USER_TMPL = """【用户输入】
{input}

【参考答案】
{expected}

【参考上下文（幻觉比对依据，可为空）】
{context}

【Agent 中间执行轨迹（工具调用/检索记录，可为空）】
{trace}

【待评回答】
{output}"""


def _extract_json(text: str) -> dict:
    """从模型输出中稳健提取 JSON（容忍代码围栏与前后缀文本）。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # 兜底：截取最外层大括号
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        return json.loads(t[start : end + 1])
    raise ValueError(f"无法解析 JSON：{text[:200]}")


class Judge:
    def __init__(self, dimensions: list[dict], mode: str = "single_call"):
        """dimensions: [{code,name,rubric,weight}]"""
        self.dims = dimensions
        self.mode = mode
        self.llm = build_judge_llm()

    def _system_prompt(self, dims: list[dict]) -> str:
        rubrics = "\n".join(f"### {d['name']}（{d['code']}）\n{d['rubric']}" for d in dims)
        schema = ",\n".join(DIM_SCHEMA.format(code=d["code"]) for d in dims)
        return SYSTEM_TMPL.format(scale=RUBRIC_SCALE, rubrics=rubrics, schema=schema)

    async def judge_case(
        self, *, case: dict, output: str, run_id: int = 0, case_key: str = ""
    ) -> list[dict]:
        """返回 [{code, score, rationale, evidence, error}]。"""
        user_msg = USER_TMPL.format(
            input=case.get("input", ""),
            expected=case.get("expected_output") or "（无）",
            context=(case.get("reference_context") or "（无）")[:4000],
            trace=json.dumps(case.get("intermediate") or [], ensure_ascii=False)[:3000],
            output=output or "（Agent 无输出）",
        )
        if self.mode == "per_dimension":
            results: list[dict] = []
            for d in self.dims:
                results.append(await self._call([d], user_msg, run_id, case_key, d["code"]))
            return results
        return self._split(await self._call(self.dims, user_msg, run_id, case_key, "all"))

    async def _call(self, dims: list[dict], user_msg: str, run_id: int, case_key: str, tag: str) -> dict:
        last_err = ""
        for attempt in range(settings.JUDGE_MAX_RETRIES + 1):
            try:
                sys_prompt = self._system_prompt(dims)
                resp = await self.llm.ainvoke([("system", sys_prompt), ("user", user_msg)])
                data = _extract_json(resp.content if isinstance(resp.content, str) else str(resp.content))
                scores = data.get("scores", data)
                if not isinstance(scores, dict):
                    raise ValueError("scores 不是对象")
                record_trace(
                    run_id, f"judge_{case_key}_{tag}",
                    name="llm-as-judge", input_data={"prompt_tail": user_msg[-500:], "tag": tag},
                    output_data=scores, tags=["judge", tag],
                )
                return scores
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
        return {"__error__": last_err}

    def _split(self, scores: dict) -> list[dict]:
        if "__error__" in scores:
            return [
                {"code": d["code"], "score": -1, "rationale": "", "evidence": "",
                 "error": str(scores["__error__"])}
                for d in self.dims
            ]
        out: list[dict] = []
        for d in self.dims:
            v = scores.get(d["code"])
            if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
                out.append({
                    "code": d["code"],
                    "score": max(0.0, min(5.0, float(v["score"]))),
                    "rationale": str(v.get("rationale", ""))[:1000],
                    "evidence": str(v.get("evidence", ""))[:1000],
                    "error": "",
                })
            else:
                out.append({"code": d["code"], "score": -1, "rationale": "", "evidence": "",
                            "error": f"Judge 输出缺少维度 {d['code']}"})
        return out
