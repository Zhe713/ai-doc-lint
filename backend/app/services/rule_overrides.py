"""规则级停用覆盖：让「停用一条规则」真的生效。

背景：内置规则没有实体可改，学习闭环确认误报时原先只能停整个规则包，
会把同包里其它正常规则一起关掉；而只在前端标「已停用」又完全不生效。
这里把停用粒度下沉到 (pack_type, rule_id)：

- user_id 为 None → 全局停用（管理员决策，对所有人生效）；
- user_id 具体 → 仅该用户自己的文档不跑这条规则。

两个消费点，同一份判定，避免各处自己实现：
1. `checkers/loader.py` 加载规则包后按条过滤（省掉无效规则的 LLM 开销）；
2. `tasks/review_pipeline.FindingCollector` 兜底过滤（覆盖 format/typo 这类
   不走规则包列表的检查器）。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rules import DisabledRule

# 规则包中「规则列表」所在的键；format 是结构化配置，没有规则列表
PACK_LIST_KEY = {
    "format": None,
    "clause": "clauses",
    "field": "fields",
    "cross": "checks",
    "typo": None,
}


def rule_item_id(item: dict) -> str | None:
    """规则条目的主键：条款/勾稽用 id，字段抽取用 key。"""
    if not isinstance(item, dict):
        return None
    return item.get("id") or item.get("key")


def _as_uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def disabled_rule_set(db: Session, user_id=None) -> set[tuple[str, str]]:
    """该用户生效的停用集合：(pack_type, rule_id)，含全局停用。"""
    uid = _as_uuid(user_id)
    stmt = select(DisabledRule.pack_type, DisabledRule.rule_id)
    if uid is not None:
        stmt = stmt.where(
            (DisabledRule.user_id.is_(None)) | (DisabledRule.user_id == uid)
        )
    else:
        stmt = stmt.where(DisabledRule.user_id.is_(None))
    return {(pt, rid) for pt, rid in db.execute(stmt).all()}


def list_disabled(db: Session, user_id=None) -> list[dict]:
    """停用明细（含来源与时间），供规则页与设置页展示。"""
    uid = _as_uuid(user_id)
    stmt = select(DisabledRule).order_by(DisabledRule.created_at.desc())
    if uid is not None:
        stmt = stmt.where(
            (DisabledRule.user_id.is_(None)) | (DisabledRule.user_id == uid)
        )
    else:
        stmt = stmt.where(DisabledRule.user_id.is_(None))
    return [
        {
            "id": str(r.id),
            "pack_type": r.pack_type,
            "rule_id": r.rule_id,
            "scope": "global" if r.user_id is None else "user",
            "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in db.execute(stmt).scalars().all()
    ]


def disable_rule(
    db: Session,
    *,
    pack_type: str,
    rule_id: str,
    user_id=None,
    reason: str | None = None,
    created_by=None,
) -> DisabledRule:
    """停用一条规则（幂等）：同 scope 已存在则复用，不重复插入。"""
    uid = _as_uuid(user_id)
    existing = db.scalar(
        select(DisabledRule).where(
            DisabledRule.pack_type == pack_type,
            DisabledRule.rule_id == rule_id,
            DisabledRule.user_id.is_(None) if uid is None else DisabledRule.user_id == uid,
        )
    )
    if existing is not None:
        if reason and not existing.reason:
            existing.reason = reason[:255]
        return existing
    row = DisabledRule(
        pack_type=pack_type,
        rule_id=rule_id[:96],
        user_id=uid,
        reason=reason[:255] if reason else None,
        created_by=_as_uuid(created_by),
    )
    db.add(row)
    db.flush()
    return row


def enable_rule(db: Session, *, pack_type: str, rule_id: str, user_id=None) -> bool:
    """恢复一条规则；返回是否真的删掉了覆盖记录。"""
    uid = _as_uuid(user_id)
    row = db.scalar(
        select(DisabledRule).where(
            DisabledRule.pack_type == pack_type,
            DisabledRule.rule_id == rule_id,
            DisabledRule.user_id.is_(None) if uid is None else DisabledRule.user_id == uid,
        )
    )
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def filter_pack_rules(pack_type: str, data: dict, disabled: set[tuple[str, str]]) -> dict:
    """按停用集合过滤规则包里的条目（format 无规则列表，原样返回）。"""
    key = PACK_LIST_KEY.get(pack_type)
    if not key or not isinstance(data, dict):
        return data
    items = data.get(key)
    if not isinstance(items, list):
        return data
    kept = [it for it in items if (pack_type, rule_item_id(it)) not in disabled]
    if len(kept) == len(items):
        return data
    return {**data, key: kept}
