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
from app.checkers.ruleset_explain import explain_pack
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


@router.post("/rules/explain")
def explain_rule_pack(
    body: dict,
    _: User = Depends(get_current_user),
):
    """把规则包翻译成人话：每条规则检查什么、不合格怎样、靠规则还是靠大模型。

    前端「规则说明」面板与「当前规则在检查什么」实时预览都调用它，
    保证解释口径只有一个来源（后端），不在前端重复硬编码。
    """
    pack_type = (body.get("pack_type") or "").strip()
    if pack_type not in PACK_TYPES:
        raise HTTPException(status_code=422, detail=f"pack_type 必须是 {', '.join(PACK_TYPES)}")
    content = body.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="规则包内容不是合法 JSON") from exc
    if not isinstance(content, dict):
        raise HTTPException(status_code=422, detail="规则包内容必须是 JSON 对象")
    try:
        return explain_pack(pack_type, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/rules/packs/builtin/{file}/explain")
def explain_builtin_pack(
    file: str,
    _: User = Depends(get_current_user),
):
    """内置包的人话解释（规则页点「这条规则在查什么」时用，无需先拿原文）。"""
    name = file.replace(".json", "").replace(".yaml", "")
    try:
        raw = _read_builtin(name)
    except RuleConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # _read_builtin 返回的是 JSON 文本，必须解析成 dict 再交给 explain_pack，
    # 否则 explain_pack 会把字符串当「非 dict」直接置空，导致内置包解释永远为空。
    if isinstance(raw, str):
        try:
            content = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"内置规则包内容损坏: {exc}") from exc
    else:
        content = raw
    if not isinstance(content, dict):
        raise HTTPException(status_code=500, detail="内置规则包内容不是 JSON 对象")
    pack_type = next((p["pack_type"] for p in BUILTIN_PACKS if p["file"] == file), None)
    if pack_type is None:
        raise HTTPException(status_code=404, detail="未找到该内置规则包的类型")
    return explain_pack(pack_type, content)


@router.post("/rules/generate")
def generate_rule_pack(
    body: dict,
    current: User = Depends(get_current_user),
):
    """自然语言生成规则包：用户用大白话描述需求，LLM 转成规则包 JSON。

    只生成并校验，不直接保存；前端预览确认后再走 POST /rules/packs 入库。
    """
    from app.llm.client import LLMCallError, LLMNotConfiguredError, chat

    description = (body.get("description") or "").strip()
    pack_type = (body.get("pack_type") or "").strip()
    doc_type = (body.get("doc_type") or "contract").strip()
    if not description:
        raise HTTPException(status_code=422, detail="请先用一句话描述要检查什么")
    if pack_type not in PACK_TYPES:
        raise HTTPException(status_code=422, detail=f"pack_type 必须是 {', '.join(PACK_TYPES)}")

    schema = ruleset_schema(pack_type)
    prompt = _build_generate_prompt(description, pack_type, doc_type, schema)
    try:
        resp = chat(
            [{"role": "user", "content": prompt}],
            scene="rule_generate", json_mode=True, temperature=0.1,
        )
    except (LLMNotConfiguredError, LLMCallError) as exc:
        raise HTTPException(status_code=503, detail=f"大模型不可用：{type(exc).__name__}") from exc

    try:
        generated = json.loads(resp.content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="大模型输出不是合法 JSON，请重试") from exc

    try:
        text = json.dumps(generated, ensure_ascii=False)
        validate_pack(pack_type, text)
    except RuleConfigError as exc:
        raise HTTPException(status_code=422, detail=f"生成的规则未通过校验：{exc}") from exc

    return {
        "pack_type": pack_type,
        "doc_type": doc_type,
        "content": generated,
        "model": resp.model,
        "valid": True,
    }


def _build_generate_prompt(description: str, pack_type: str, doc_type: str, schema: dict) -> str:
    field_lines = []
    for f in schema.get("fields", []):
        line = f"- {f['key']}（{f['label']}，{f['type']}）"
        if f.get("help"):
            line += f"：{f['help']}"
        if f.get("example"):
            line += f"。示例：{f['example']}"
        field_lines.append(line)
    list_key = {"clause": "clauses", "field": "fields", "cross": "checks"}.get(pack_type)
    lines = [
        f"你是规则配置助手。请把用户的自然语言需求转成一个「{schema['label']}」的 JSON 规则包。",
        f"文档类型 doc_type 为 {doc_type}。",
        "只输出 JSON 对象，不要解释。",
        "",
        "字段说明：",
        "\n".join(field_lines),
        "",
    ]
    if list_key:
        lines.append(
            f"输出结构必须是：{{\"version\":1,\"doc_types\":[\"{doc_type}\"],\"{list_key}\":[...]}}，"
            "列表中的每个对象严格使用上面的字段键名。"
        )
        lines.append("根据用户需求生成合适的条目，关键词要贴合中文合同的真实写法。")
    else:
        lines.append("输出结构必须是 version=1 的格式规则对象，严格使用上面的字段键名。")
    lines.append("")
    lines.append(f"用户需求：{description}")
    return "\n".join(lines)


@router.get("/rules/disabled")
def list_disabled_rules(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """当前生效的规则停用清单（全局停用 + 自己的停用）。"""
    from app.services.rule_overrides import list_disabled

    return {"items": list_disabled(db, current.id)}


@router.post("/rules/disabled", status_code=201)
def disable_single_rule(
    body: dict,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """停用单条规则：scope=user（只影响自己的文档）或 global（管理员，全员）。"""
    from app.checkers.loader import invalidate_pack_caches
    from app.services.rule_overrides import disable_rule

    pack_type = (body.get("pack_type") or "").strip()
    rule_id = (body.get("rule_id") or "").strip()
    scope = (body.get("scope") or "user").strip()
    if pack_type not in PACK_TYPES:
        raise HTTPException(status_code=422, detail=f"pack_type 必须是 {', '.join(PACK_TYPES)}")
    if not rule_id:
        raise HTTPException(status_code=422, detail="rule_id 不能为空")
    if scope not in ("user", "global"):
        raise HTTPException(status_code=422, detail="scope 仅支持 user / global")
    if scope == "global" and not current.is_superuser and "admin" not in current.role_names:
        raise HTTPException(status_code=403, detail="全局停用需要管理员权限")

    row = disable_rule(
        db, pack_type=pack_type, rule_id=rule_id,
        user_id=None if scope == "global" else current.id,
        reason=(body.get("reason") or "").strip() or None,
        created_by=current.id,
    )
    db.commit()
    invalidate_pack_caches()
    return {"ok": True, "id": str(row.id), "pack_type": pack_type,
            "rule_id": rule_id, "scope": scope}


@router.delete("/rules/disabled")
def enable_single_rule(
    pack_type: str,
    rule_id: str,
    scope: str = "user",
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """恢复单条规则（撤销停用）。"""
    from app.checkers.loader import invalidate_pack_caches
    from app.services.rule_overrides import enable_rule

    if pack_type not in PACK_TYPES:
        raise HTTPException(status_code=422, detail=f"pack_type 必须是 {', '.join(PACK_TYPES)}")
    if scope == "global" and not current.is_superuser and "admin" not in current.role_names:
        raise HTTPException(status_code=403, detail="恢复全局停用需要管理员权限")
    ok = enable_rule(db, pack_type=pack_type, rule_id=rule_id,
                     user_id=None if scope == "global" else current.id)
    db.commit()
    invalidate_pack_caches()
    if not ok:
        raise HTTPException(status_code=404, detail="该规则当前没有被停用")
    return {"ok": True}


@router.get("/rules/packs")
def list_rule_packs(
    pack_type: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    stmt = select(RulePack).order_by(RulePack.updated_at.desc())
    # 越权保护：非管理员只能看到自己创建的规则包，不能枚举他人私有规则内容
    if not current.is_superuser and "admin" not in current.role_names:
        stmt = stmt.where(RulePack.user_id == current.id)
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
    if p.user_id != current.id and not current.is_superuser and "admin" not in current.role_names:
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
    current: User = Depends(get_current_user),
):
    p = db.get(RulePack, pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="规则包不存在")
    if p.user_id != current.id and not current.is_superuser and "admin" not in current.role_names:
        raise HTTPException(status_code=403, detail="只能编辑自己创建的规则包")
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
    current: User = Depends(get_current_user),
):
    p = db.get(RulePack, pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="规则包不存在")
    if p.user_id != current.id and not current.is_superuser and "admin" not in current.role_names:
        raise HTTPException(status_code=403, detail="只能操作自己创建的规则包")
    p.enabled = bool(body.get("enabled", not p.enabled))
    db.commit()
    db.refresh(p)
    invalidate_pack_caches()
    return _pack_out(p)


@router.delete("/rules/packs/{pack_id}", status_code=204)
def delete_rule_pack(
    pack_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    p = db.get(RulePack, pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="规则包不存在")
    if p.user_id != current.id and not current.is_superuser and "admin" not in current.role_names:
        raise HTTPException(status_code=403, detail="只能删除自己创建的规则包")
    db.delete(p)
    db.commit()
    invalidate_pack_caches()
    return None
