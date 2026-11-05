"""规则级停用：记录幂等、作用域隔离、规则包过滤、收集器兜底。"""

import uuid

from app.core.security import hash_password
from app.models.document import Document, DocumentTask
from app.models.user import User
from app.services import rule_overrides
from app.tasks.review_pipeline import FindingCollector
from conftest import TestSessionLocal


def _user(db, *, admin: bool = False) -> User:
    user = User(
        username=f"ovr_{uuid.uuid4().hex[:10]}",
        password_hash=hash_password("MemberPass123"),
        is_superuser=admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _task(db, user: User) -> DocumentTask:
    doc = Document(
        user_id=user.id,
        filename="ovr.txt",
        storage_key=f"test/{uuid.uuid4().hex}.txt",
        sha256=uuid.uuid4().hex * 2,
        size_bytes=10,
        ext="txt",
        doc_type="contract",
    )
    db.add(doc)
    db.flush()
    task = DocumentTask(document_id=doc.id, user_id=user.id, task_type="review")
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_disable_is_idempotent_and_scoped():
    db = TestSessionLocal()
    try:
        admin = _user(db, admin=True)
        other = _user(db)

        first = rule_overrides.disable_rule(
            db, pack_type="format", rule_id="format.page.size", created_by=admin.id
        )
        again = rule_overrides.disable_rule(db, pack_type="format", rule_id="format.page.size")
        db.commit()
        assert first.id == again.id, "重复停用同一条规则不应产生第二条记录"

        # 全局停用对所有人生效
        assert ("format", "format.page.size") in rule_overrides.disabled_rule_set(db, other.id)

        # 个人停用只影响本人
        rule_overrides.disable_rule(
            db, pack_type="typo", rule_id="typo.common", user_id=other.id
        )
        db.commit()
        assert ("typo", "typo.common") in rule_overrides.disabled_rule_set(db, other.id)
        assert ("typo", "typo.common") not in rule_overrides.disabled_rule_set(db, admin.id)

        assert rule_overrides.enable_rule(
            db, pack_type="typo", rule_id="typo.common", user_id=other.id
        )
        db.commit()
        assert ("typo", "typo.common") not in rule_overrides.disabled_rule_set(db, other.id)
    finally:
        db.close()


def test_filter_pack_rules_drops_only_disabled_items():
    data = {
        "clauses": [
            {"id": "custom_1", "name": "付款"},
            {"id": "custom_2", "name": "违约"},
        ]
    }
    filtered = rule_overrides.filter_pack_rules("clause", data, {("clause", "custom_1")})
    assert [item["id"] for item in filtered["clauses"]] == ["custom_2"]

    # format 是结构化配置，没有规则列表，loader 层原样返回、由收集器兜底
    assert rule_overrides.filter_pack_rules(
        "format", {"page": {}}, {("format", "format.page.size")}
    ) == {"page": {}}


def test_collector_suppresses_and_records_disabled_rule():
    db = TestSessionLocal()
    try:
        user = _user(db)
        task = _task(db, user)
        collector = FindingCollector(
            db, task, {("format", "format.page.size"), ("clause", "custom_6")}
        )

        kept = collector.add(checker="format", rule_id="format.font.body", message="正文字体不合规")
        dropped = collector.add(checker="format", rule_id="format.page.size", message="纸张不是 A4")

        assert kept is not None and kept.rule_id == "format.font.body"
        assert dropped is None, "已停用的规则不能再产出 finding"
        assert collector.suppressed == ["format.page.size"], "被抑制的规则要留痕，不能悄悄消失"
        assert [f.rule_id for f in collector.items] == ["format.font.body"]
    finally:
        db.close()
