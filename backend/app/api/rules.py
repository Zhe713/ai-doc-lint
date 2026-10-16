"""规则包管理 API（W6 Day26 / P2-3 JSON 数据化）。

- 内置包只读展示（source=builtin，JSON 数据化）；自定义包入库（source=custom）；
- 启用的自定义包优先于内置（loader 已改造），变更后清加载缓存立即生效；
- /rules/schemas 返回四类规则包的表单化 schema，供规则管理界面（P3）渲染表单替代手写 YAML。
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.checkers.loader import (
    CLAUSE_PACKS,
    CROSS_PACKS,
    DEFAULT_FORMAT_RULES,
    FIELD_PACKS,
    _read_builtin,
    invalidate_pack_caches,
)
from app.checkers.ruleset_schema import all_ruleset_schemas, ruleset_schema
from app.checkers.validate import RuleConfigError, validate_pack
from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.rules import PACK_TYPES, RulePack
from app.models.user import User

router = APIRouter(tags=["rules"])

BUILTIN_PACKS = [
    {"name": "格式默认规则包", "pack_type": "format", "doc_type": "global",
     "file": f"{DEFAULT_FORMAT_RULES}.json"},
    {"name": "条款完整性·合同", "pack_type": "clause", "doc_type": "contract",
     "file": f"{CLAUSE_PACKS['contract']}.json"},
    {"name": "字段抽取·合同", "pack_type": "field", "doc_type": "contract",
     "file": f"{FIELD_PACKS['contract']}.json"},
    {"name": "交叉勾稽·合同", "pack_type": "cross", "doc_type": "contract",
     "file": f"{CROSS_PACKS['contract']}.json"},
]

_MAX_YAML = 200_000  # 单包内容上限 200KB（JSON/YAML 同限）


def _pack_out(p: RulePack) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "pack_type": p.pack_type,
        "doc_type": p.doc_type,
        "description": p.description,
        "version": p.version,
        "enabled": p.enabled,
        "source": "custom",
        "yaml_content": p.yaml_content,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/rules/packs/builtin")
def list_builtin_packs(
    _: User = Depends(get_current_user),
):
    return BUILTIN_PACKS


@router.get("/rules/packs/builtin/{file}")
def builtin_pack_content(
    file: str,
    _: User = Depends(get_current_user),
):
    """返回内置规则包原文（JSON）。"""
    name = file.replace(".json", "").replace(".yaml", "")
    try:
        return {"name": name, "file": file, "content": _read_builtin(name)}
    except RuleConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/rules/schemas")
def ruleset_schemas(_: User = Depends(get_current_user)):
    """四类规则包的表单化 schema（P3 规则管理界面渲染用）。"""
    return {"schemas": all_ruleset_schemas()}


@router.get("/rules/packs")
def list_rule_packs(
    pack_type: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    stmt = select(RulePack).order_by(RulePack.updated_at.desc())
    if pack_type:
        if pack_type not in PACK_TYPES:
            raise HTTPException(status_code=422, detail=f"未知包类型: {pack_type}")
        stmt = stmt.where(RulePack.pack_type == pack_type)
    rows = db.execute(stmt).scalars().all()
    return [_pack_out(p) for p in rows]


@router.get("/rules/packs/{pack_id}")
def rule_pack_detail(
    pack_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    p = db.get(RulePack, pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="规则包不存在")
    return _pack_out(p)


@router.post("/rules/packs", status_code=201)
def create_rule_pack(
    body: dict,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    name = (body.get("name") or "").strip()
    pack_type = (body.get("pack_type") or "").strip()
    doc_type = (body.get("doc_type") or "global").strip()
    yaml_content = body.get("yaml_content") or ""
    if not name:
        raise HTTPException(status_code=422, detail="规则包名称不能为空")
    if pack_type not in PACK_TYPES:
        raise HTTPException(status_code=422, detail=f"未知包类型: {pack_type}")
    if len(yaml_content) > _MAX_YAML:
        raise HTTPException(status_code=422, detail="规则包内容超过 200KB 上限")
    try:
        validate_pack(pack_type, yaml_content)
    except RuleConfigError as exc:
        raise HTTPException(status_code=422, detail=f"规则包校验失败: {exc}")

    p = RulePack(
        user_id=current.id,
        name=name,
        pack_type=pack_type,
        doc_type=doc_type,
        description=(body.get("description") or "").strip() or None,
        version=body.get("version") or 1,
        yaml_content=yaml_content,
        enabled=bool(body.get("enabled", True)),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    invalidate_pack_caches()
    return _pack_out(p)


@router.put("/rules/packs/{pack_id}")
def update_rule_pack(
    pack_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    p = db.get(RulePack, pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="规则包不存在")
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="规则包名称不能为空")
        p.name = name
    if "description" in body:
        p.description = (body.get("description") or "").strip() or None
    if "yaml_content" in body:
        yaml_content = body.get("yaml_content") or ""
        if len(yaml_content) > _MAX_YAML:
            raise HTTPException(status_code=422, detail="规则包内容超过 200KB 上限")
        try:
            validate_pack(p.pack_type, yaml_content)
        except RuleConfigError as exc:
            raise HTTPException(status_code=422, detail=f"规则包校验失败: {exc}")
        p.yaml_content = yaml_content
        p.version = (p.version or 1) + 1
    db.commit()
    db.refresh(p)
    invalidate_pack_caches()
    return _pack_out(p)


@router.patch("/rules/packs/{pack_id}/toggle")
def toggle_rule_pack(
    pack_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    p = db.get(RulePack, pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="规则包不存在")
    p.enabled = bool(body.get("enabled", not p.enabled))
    db.commit()
    db.refresh(p)
    invalidate_pack_caches()
    return _pack_out(p)


@router.delete("/rules/packs/{pack_id}", status_code=204)
def delete_rule_pack(
    pack_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    p = db.get(RulePack, pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="规则包不存在")
    db.delete(p)
    db.commit()
    invalidate_pack_caches()
    return None
