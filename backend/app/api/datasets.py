"""评测集管理路由：草稿编辑 → 导入预检 → 质检 → 发布冻结版本 → 导出。

版本模型：每个数据集恒有一个 version='draft' 的工作版本（可增删改样本）；
「发布」把草稿复制为不可变快照版本 v1/v2/…，评测任务只能引用已发布版本。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.governance.quality import check_dataset, summarize
from app.models import Dataset, DatasetVersion, EvalCase, QualityReport, TagDict
from app.schemas import CaseIn, CaseUpdate, DatasetCreate, ImportIn, PublishIn

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _get_draft(db: Session, ds: Dataset) -> DatasetVersion:
    draft = next((v for v in ds.versions if v.version == "draft"), None)
    if draft is None:
        draft = DatasetVersion(dataset_id=ds.id, version="draft")
        db.add(draft)
        db.commit()
        db.refresh(ds)
    return draft


def _valid_tags(db: Session) -> dict[str, set[str]]:
    tags = db.execute(select(TagDict).where(TagDict.enabled.is_(True))).scalars().all()
    out: dict[str, set[str]] = {}
    for t in tags:
        out.setdefault(t.category, set()).add(t.value)
    return out


def _case_out(c: EvalCase) -> dict:
    return {
        "id": c.id, "seq": c.seq, "input": c.input, "expected_output": c.expected_output,
        "reference_context": c.reference_context, "tools_spec": json.loads(c.tools_spec or "{}"),
        "difficulty": c.difficulty, "tags": json.loads(c.tags or "{}"),
        "meta": json.loads(c.meta or "{}"),
    }


def _version_out(v: DatasetVersion, with_cases: bool = False) -> dict:
    out = {"id": v.id, "version": v.version, "note": v.note, "case_count": v.case_count,
           "quality_summary": json.loads(v.quality_summary or "{}"),
           "created_at": v.created_at.isoformat(), "is_draft": v.version == "draft"}
    if with_cases:
        out["cases"] = [_case_out(c) for c in sorted(v.cases, key=lambda x: x.seq)]
    return out


@router.get("")
def list_datasets(db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for ds in db.execute(select(Dataset).order_by(Dataset.id)).scalars():
        published = [v for v in ds.versions if v.version != "draft"]
        draft = _get_draft(db, ds)
        out.append({
            "id": ds.id, "name": ds.name, "description": ds.description,
            "target_types": ds.target_types,
            "draft_count": len(draft.cases),
            "versions": [{"id": v.id, "version": v.version, "case_count": v.case_count,
                          "created_at": v.created_at.isoformat()} for v in published],
        })
    return out


@router.post("", status_code=201)
def create_dataset(body: DatasetCreate, db: Session = Depends(get_db)) -> dict:
    if db.query(Dataset).filter_by(name=body.name).first():
        raise HTTPException(409, f"数据集已存在: {body.name}")
    ds = Dataset(name=body.name, description=body.description, target_types=body.target_types)
    db.add(ds)
    db.flush()
    db.add(DatasetVersion(dataset_id=ds.id, version="draft"))
    db.commit()
    return {"id": ds.id}


@router.get("/{ds_id}")
def get_dataset(ds_id: int, db: Session = Depends(get_db)) -> dict:
    ds = db.get(Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "数据集不存在")
    draft = _get_draft(db, ds)
    return {
        "id": ds.id, "name": ds.name, "description": ds.description,
        "target_types": ds.target_types,
        "draft": _version_out(draft, with_cases=True),
        "versions": [_version_out(v) for v in ds.versions if v.version != "draft"],
    }


@router.delete("/{ds_id}")
def delete_dataset(ds_id: int, db: Session = Depends(get_db)) -> dict:
    ds = db.get(Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "数据集不存在")
    db.delete(ds)
    db.commit()
    return {"ok": True}


# ---------- 样本 CRUD（草稿） ----------

def _add_case(db: Session, draft: DatasetVersion, c: CaseIn) -> EvalCase:
    case = EvalCase(
        dataset_version_id=draft.id,
        seq=max([x.seq for x in draft.cases], default=0) + 1,
        input=c.input, expected_output=c.expected_output,
        reference_context=c.reference_context,
        tools_spec=json.dumps(c.tools_spec, ensure_ascii=False),
        difficulty=c.difficulty, tags=json.dumps(c.tags, ensure_ascii=False),
        meta=json.dumps(c.meta, ensure_ascii=False),
    )
    db.add(case)
    return case


@router.post("/{ds_id}/cases", status_code=201)
def add_case(ds_id: int, body: CaseIn, db: Session = Depends(get_db)) -> dict:
    ds = db.get(Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "数据集不存在")
    draft = _get_draft(db, ds)
    issues = [i.as_dict() for i in check_dataset(
        [body.model_dump()], valid_tags=_valid_tags(db), target_types=ds.target_types
    ) if i.level == "blocker"]
    if issues:
        raise HTTPException(422, {"message": "样本未通过质检（blocker）", "issues": issues})
    case = _add_case(db, draft, body)
    db.commit()
    return _case_out(case)


@router.put("/{ds_id}/cases/{case_id}")
def update_case(ds_id: int, case_id: int, body: CaseUpdate, db: Session = Depends(get_db)) -> dict:
    case = db.get(EvalCase, case_id)
    if not case or case.dataset_version.dataset_id != ds_id or case.dataset_version.version != "draft":
        raise HTTPException(404, "草稿样本不存在")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(case, field, val if not isinstance(val, dict) else json.dumps(val, ensure_ascii=False))
    db.commit()
    return _case_out(case)


@router.delete("/{ds_id}/cases/{case_id}")
def delete_case(ds_id: int, case_id: int, db: Session = Depends(get_db)) -> dict:
    case = db.get(EvalCase, case_id)
    if not case or case.dataset_version.dataset_id != ds_id or case.dataset_version.version != "draft":
        raise HTTPException(404, "草稿样本不存在")
    db.delete(case)
    db.commit()
    return {"ok": True}


# ---------- JSON 批量导入（预检 → 确认两步） ----------

@router.post("/{ds_id}/import")
def import_cases(ds_id: int, body: ImportIn, db: Session = Depends(get_db)) -> dict:
    """confirm=false：仅预检返回问题清单；confirm=true：校验通过后落库。"""
    ds = db.get(Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "数据集不存在")
    draft = _get_draft(db, ds)
    dicts = [c.model_dump() for c in body.cases]
    # 预检 = 新样本 + 既有草稿（近似重复要跨集合判断）
    existing = [_case_out(c) for c in draft.cases]
    merged = existing + dicts
    for i, d in enumerate(dicts, start=len(existing)):
        d["seq"] = i + 1
    issues = check_dataset(merged, valid_tags=_valid_tags(db), target_types=ds.target_types)
    summary = summarize(issues)
    if not body.confirm:
        return {"confirm_required": True, "quality": summary,
                "to_import": len(dicts), "draft_existing": len(existing)}
    if summary["blockers"] > 0:
        raise HTTPException(422, {"message": "存在阻断问题，未导入", "quality": summary})
    for c in body.cases:
        _add_case(db, draft, c)
    db.commit()
    qr = QualityReport(dataset_id=ds.id, triggered_by="import",
                       blockers=0, warnings=summary["warnings"],
                       issues=json.dumps(summary["issues"], ensure_ascii=False))
    db.add(qr)
    db.commit()
    return {"imported": len(body.cases), "quality": summary}


# ---------- 发布 / 版本 / 导出 ----------

def _run_quality(db: Session, ds: Dataset, draft: DatasetVersion) -> dict:
    cases = [_case_out(c) for c in draft.cases]
    issues = check_dataset(cases, valid_tags=_valid_tags(db), target_types=ds.target_types)
    return summarize(issues)


@router.post("/{ds_id}/quality-check")
def quality_check(ds_id: int, db: Session = Depends(get_db)) -> dict:
    ds = db.get(Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "数据集不存在")
    draft = _get_draft(db, ds)
    summary = _run_quality(db, ds, draft)
    qr = QualityReport(dataset_id=ds.id, triggered_by="manual",
                       blockers=summary["blockers"], warnings=summary["warnings"],
                       issues=json.dumps(summary["issues"], ensure_ascii=False))
    db.add(qr)
    db.commit()
    return {"quality_report_id": qr.id, **summary}


@router.post("/{ds_id}/publish")
def publish(ds_id: int, body: PublishIn, db: Session = Depends(get_db)) -> dict:
    ds = db.get(Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "数据集不存在")
    draft = _get_draft(db, ds)
    if not draft.cases:
        raise HTTPException(400, "草稿为空，无法发布")
    summary = _run_quality(db, ds, draft)
    if summary["blockers"] > 0:
        raise HTTPException(409, {"message": "存在阻断问题，须修复后发布", "quality": summary})
    nums = [int(v.version.lstrip("v")) for v in (x.version for x in ds.versions) if v.version != "draft"]
    new_ver = f"v{max(nums, default=0) + 1}"
    snap = DatasetVersion(
        dataset_id=ds.id, version=new_ver, note=body.note,
        case_count=len(draft.cases),
        quality_summary=json.dumps(
            {"blockers": summary["blockers"], "warnings": summary["warnings"],
             "by_rule": summary["by_rule"]}, ensure_ascii=False),
    )
    db.add(snap)
    db.flush()
    for c in sorted(draft.cases, key=lambda x: x.seq):
        db.add(EvalCase(
            dataset_version_id=snap.id, seq=c.seq, input=c.input,
            expected_output=c.expected_output, reference_context=c.reference_context,
            tools_spec=c.tools_spec, difficulty=c.difficulty, tags=c.tags, meta=c.meta,
        ))
    qr = QualityReport(dataset_id=ds.id, triggered_by="publish",
                       blockers=0, warnings=summary["warnings"],
                       issues=json.dumps(summary["issues"], ensure_ascii=False))
    db.add(qr)
    db.commit()
    return _version_out(snap)


@router.get("/{ds_id}/versions")
def list_versions(ds_id: int, db: Session = Depends(get_db)) -> list[dict]:
    ds = db.get(Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "数据集不存在")
    return [_version_out(v) for v in ds.versions]


@router.get("/{ds_id}/versions/{v_id}")
def get_version(ds_id: int, v_id: int, db: Session = Depends(get_db)) -> dict:
    v = db.get(DatasetVersion, v_id)
    if not v or v.dataset_id != ds_id:
        raise HTTPException(404, "版本不存在")
    return _version_out(v, with_cases=True)


@router.get("/{ds_id}/versions/{v_id}/export")
def export_version(ds_id: int, v_id: int, db: Session = Depends(get_db)) -> dict:
    v = db.get(DatasetVersion, v_id)
    if not v or v.dataset_id != ds_id:
        raise HTTPException(404, "版本不存在")
    cases = [_case_out(c) for c in sorted(v.cases, key=lambda x: x.seq)]
    for c in cases:
        c.pop("id", None)
        c.pop("seq", None)
    return {"dataset": v.dataset.name, "version": v.version, "cases": cases}


# ---------- 版本对比（升级可视化） ----------

def diff_cases(old: list[dict], new: list[dict]) -> dict:
    """以 input 文本为对齐键对比两版样本：新增/删除/修改（期望输出/难度/标签变化）。

    纯函数、乱序稳定；input 相同即视为同一样本（与 replay 对比口径一致）。
    """
    old_map = {c["input"]: c for c in old}
    new_map = {c["input"]: c for c in new}

    def sig(c: dict) -> tuple:
        return (c.get("expected_output"), c.get("difficulty"), c.get("tags") or {})

    added = [c for k, c in new_map.items() if k not in old_map]
    removed = [c for k, c in old_map.items() if k not in new_map]
    changed = [
        {"old": old_map[k], "new": c}
        for k, c in new_map.items()
        if k in old_map and sig(old_map[k]) != sig(c)
    ]
    return {
        "added": added, "removed": removed, "changed": changed,
        "unchanged": len(new_map) - len(added) - len(changed),
    }


def _version_cases(db: Session, ds_id: int, v_id: int) -> tuple[DatasetVersion, list[dict]]:
    v = db.get(DatasetVersion, v_id)
    if not v or v.dataset_id != ds_id:
        raise HTTPException(404, "版本不存在")
    return v, [_case_out(c) for c in sorted(v.cases, key=lambda x: x.seq)]


@router.get("/{ds_id}/versions/{a_id}/diff/{b_id}")
def diff_versions(ds_id: int, a_id: int, b_id: int, db: Session = Depends(get_db)) -> dict:
    """任意两个版本对比（a=旧，b=新；可含 draft）。"""
    _, old_cases = _version_cases(db, ds_id, a_id)
    _, new_cases = _version_cases(db, ds_id, b_id)
    return diff_cases(old_cases, new_cases)


@router.get("/{ds_id}/draft-diff")
def diff_draft(ds_id: int, db: Session = Depends(get_db)) -> dict:
    """草稿相对最近已发布版本的 diff——发布前预览「这次升级改了什么」。"""
    ds = db.get(Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "数据集不存在")
    draft = _get_draft(db, ds)
    published = [v for v in ds.versions if v.version != "draft"]
    if not published:
        return diff_cases([], [_case_out(c) for c in sorted(draft.cases, key=lambda x: x.seq)])
    latest = max(published, key=lambda v: int(v.version.lstrip("v")))
    _, old_cases = _version_cases(db, ds_id, latest.id)
    return diff_cases(old_cases, [_case_out(c) for c in sorted(draft.cases, key=lambda x: x.seq)])
