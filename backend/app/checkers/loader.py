"""格式/条款/字段/勾稽规则包加载（W6 Day26 改造）。

加载顺序：启用中的 DB 自定义包（rule_packs 表）优先 → 无则回落内置 YAML。
- 上传/启停/更新自定义包后调用 invalidate_pack_caches() 清 lru_cache；
- 校验逻辑统一走 validate.validate_pack_yaml（纯函数，上传 API 复用）。
"""

import functools
from pathlib import Path

from app.checkers.validate import (
    PACK_TYPES,
    RuleConfigError,
    pack_sub_payload,
    validate_pack_yaml,
)

RULES_DIR = Path(__file__).parent / "rules"
DEFAULT_FORMAT_RULES = "format_default.yaml"
CLAUSE_PACKS = {
    "contract": "clause_contract.yaml",
}
FIELD_PACKS = {
    "contract": "fields_contract.yaml",
}
CROSS_PACKS = {
    "contract": "cross_contract.yaml",
}

# 可替换的会话工厂：测试注入 TestSessionLocal 以覆盖 DB 优先路径
_SESSION_FACTORY = None


def _db_session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        from app.db.session import SessionLocal
        _SESSION_FACTORY = SessionLocal
    return _SESSION_FACTORY


def _db_custom_yaml(pack_type: str, doc_type: str) -> str | None:
    """查询启用中的自定义规则包 YAML（最新一条）；无则 None。"""
    if pack_type not in PACK_TYPES:
        return None
    from app.models.rules import RulePack

    db = _db_session_factory()()
    try:
        row = (
            db.query(RulePack)
            .filter(
                RulePack.pack_type == pack_type,
                RulePack.doc_type == doc_type,
                RulePack.enabled.is_(True),
            )
            .order_by(RulePack.updated_at.desc())
            .first()
        )
        return row.yaml_content if row else None
    except Exception:  # noqa: BLE001  表未迁移/库不可用时回落内置包
        return None
    finally:
        db.close()


def _load_custom_or_builtin(pack_type: str, doc_type: str,
                            builtin_name: str | None) -> dict:
    """自定义包优先；内置文件兜底。返回校验后的 dict。"""
    custom = _db_custom_yaml(pack_type, doc_type)
    if custom is not None:
        return validate_pack_yaml(pack_type, custom)
    if builtin_name is None:
        raise RuleConfigError(f"内置规则包不存在: {pack_type}/{doc_type}")
    path = RULES_DIR / builtin_name
    if not path.exists():
        raise RuleConfigError(f"规则包文件不存在: {path}")
    return validate_pack_yaml(pack_type, path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=8)
def load_format_rules(name: str = DEFAULT_FORMAT_RULES) -> dict:
    """格式规则包（DB 自定义 format 包优先，doc_type=global）。"""
    data = _load_custom_or_builtin("format", "global", name)
    return data


@functools.lru_cache(maxsize=8)
def load_clause_pack(doc_type: str) -> list[dict]:
    """按文档类型加载条款规则包；该类型无包时返回空列表（调用方据此 skip）。"""
    name = CLAUSE_PACKS.get(doc_type)
    try:
        data = _load_custom_or_builtin("clause", doc_type, name)
        return pack_sub_payload("clause", data)
    except RuleConfigError:
        if name is None:
            return []
        raise


@functools.lru_cache(maxsize=8)
def load_field_pack(doc_type: str) -> list[dict]:
    """按文档类型加载字段抽取规则包；该类型无包时返回空列表。"""
    name = FIELD_PACKS.get(doc_type)
    try:
        data = _load_custom_or_builtin("field", doc_type, name)
        return pack_sub_payload("field", data)
    except RuleConfigError:
        if name is None:
            return []
        raise


@functools.lru_cache(maxsize=8)
def load_cross_rules(doc_type: str) -> dict | None:
    """按文档类型加载交叉比对规则包；该类型无包时返回 None。"""
    name = CROSS_PACKS.get(doc_type)
    try:
        return _load_custom_or_builtin("cross", doc_type, name)
    except RuleConfigError:
        if name is None:
            return None
        raise


def invalidate_pack_caches() -> None:
    """自定义规则包变更后清空全部加载缓存（量小，全清最稳）。"""
    load_format_rules.cache_clear()
    load_clause_pack.cache_clear()
    load_field_pack.cache_clear()
    load_cross_rules.cache_clear()
