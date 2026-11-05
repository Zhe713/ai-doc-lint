"""ClauseChecker 测试：规则预筛、弱信号判定、缺失语义确认、反幻觉护栏、无包跳过。

三层口径（与实现一致）：
- strong 命中 → 视为存在，0 token；
- 仅 weak 命中 → LLM 判定「存在但不完整」（source=hybrid）；
- 强弱都无 → LLM 按章节语义确认是否真的缺失（source=llm），确认不了不报。
"""

import json
import uuid
from types import SimpleNamespace

import pytest

from app.checkers.clause_checker import ClauseChecker
from app.db import storage
from app.llm.client import LLMNotConfiguredError
from app.models.document import (
    FINDING_SOURCE_HYBRID,
    FINDING_SOURCE_LLM,
    Artifact,
    Document,
)
from app.tasks.review_pipeline import FindingCollector
from conftest import TestSessionLocal
from tests.test_intake import _make_user


@pytest.fixture(autouse=True)
def _loader_uses_test_db(monkeypatch):
    """规则包加载走测试库，避免主库自定义包污染断言（rule_id 变 custom_N）。"""
    from app.checkers import loader

    monkeypatch.setattr(loader, "_SESSION_FACTORY", TestSessionLocal)
    loader.invalidate_pack_caches()


# LLM 桩：返回一条或多条 clause 判定（clause_id + status + quote + reason）
def _llm(*rows) -> SimpleNamespace:
    return SimpleNamespace(
        content=json.dumps({"results": list(rows)}, ensure_ascii=False),
        model="stub-model",
    )


def _absent(clause_id: str, reason: str = "") -> dict:
    return {"clause_id": clause_id, "status": "absent", "quote": "", "reason": reason}


GOOD_CONTRACT = """
买卖合同
甲方：某某科技有限公司
乙方：某某贸易有限公司
第一条 合同标的：办公设备一批。
第二条 数量：共计 10 台。
第三条 合同总价：人民币伍万元整（¥50000）。
第四条 交付时间：合同签订后 10 日内交付。
第五条 违约责任：任何一方违约，应向守约方支付违约金并赔偿损失。
第六条 争议解决：协商不成的，提交仲裁委员会仲裁。
本合同自双方盖章之日起生效。
"""


def _setup(doc_text: str, *, doc_type="contract", username=None):
    db = TestSessionLocal()
    username = username or f"clause_{uuid.uuid4().hex[:8]}"
    _make_user(username)
    from app.models.user import User

    user = db.query(User).filter(User.username == username).one()

    doc = Document(
        user_id=user.id, filename="contract.txt",
        storage_key=f"docs/{user.id}/orig.txt", sha256="x" * 64,
        size_bytes=len(doc_text), content_type="text/plain",
        ext="txt", doc_type=doc_type, status="parsed",
    )
    db.add(doc)
    db.flush()

    key = f"artifacts/{doc.id}/plaintext.txt"
    storage.put_object(key, doc_text.encode("utf-8"), content_type="text/plain")
    db.add(Artifact(document_id=doc.id, kind="plaintext", storage_key=key))
    db.commit()

    task = SimpleNamespace(id=uuid.uuid4(), document_id=doc.id, user_id=user.id)
    collector = FindingCollector(db, task)
    return db, doc, collector


def _run(doc_text, *, doc_type="contract"):
    db, doc, collector = _setup(doc_text, doc_type=doc_type)
    ClauseChecker(db, doc, collector).run()
    db.close()
    return collector


def test_good_contract_no_llm(monkeypatch):
    called = []
    monkeypatch.setattr("app.checkers.clause_checker.chat",
                        lambda *a, **k: called.append(1))
    collector = _run(GOOD_CONTRACT)
    assert collector.items == []
    assert called == []  # 全部 strong 命中，0 token


MISSING_BOTH = GOOD_CONTRACT.replace(
    "第五条 违约责任：任何一方违约，应向守约方支付违约金并赔偿损失。\n", ""
).replace(
    "第六条 争议解决：协商不成的，提交仲裁委员会仲裁。\n", ""
)

# 违约责任只剩弱信号「逾期」，争议解决整条删除
WEAK_BREACH = GOOD_CONTRACT.replace(
    "第五条 违约责任：任何一方违约，应向守约方支付违约金并赔偿损失。",
    "第五条 逾期交付的，双方另行协商。",
).replace(
    "第六条 争议解决：协商不成的，提交仲裁委员会仲裁。\n", ""
)


def test_missing_clause_confirmed_by_llm(monkeypatch):
    """强弱信号都没有 → 交 LLM 语义确认；确认缺失才报，且标 source=llm。"""
    monkeypatch.setattr(
        "app.checkers.clause_checker.chat",
        lambda *a, **k: _llm(
            _absent("clause.breach", "全文无违约责任约定"),
            _absent("clause.dispute", "全文无争议解决约定"),
        ),
    )
    collector = _run(MISSING_BOTH)
    assert {f.rule_id for f in collector.items} == {"clause.breach", "clause.dispute"}
    assert all(f.source == FINDING_SOURCE_LLM for f in collector.items)
    assert all(f.severity == "warning" for f in collector.items)
    assert all(f.llm_model == "stub-model" for f in collector.items)


def test_missing_clause_found_by_semantics(monkeypatch):
    """关键词没命中但 LLM 在章节里找到同义条款 → 不判缺失（不误报）。"""
    monkeypatch.setattr(
        "app.checkers.clause_checker.chat",
        lambda *a, **k: _llm(
            {"clause_id": "clause.breach", "status": "present",
             "quote": "第四条 交付时间", "reason": "已有逾期交付责任约定"},
            {"clause_id": "clause.dispute", "status": "present",
             "quote": "", "reason": "已有协商与仲裁安排"},
        ),
    )
    collector = _run(MISSING_BOTH)
    assert collector.items == []


def test_weak_signal_llm_confirms_missing(monkeypatch):
    """仅弱信号命中 → LLM 判「存在但不完整」，source=hybrid。"""
    monkeypatch.setattr(
        "app.checkers.clause_checker.chat",
        lambda *a, **k: _llm(
            {"clause_id": "clause.breach", "status": "missing", "quote": "",
             "reason": "仅有逾期表述，无违约责任约定"},
        ),
    )
    collector = _run(WEAK_BREACH)
    breach = [f for f in collector.items if f.rule_id == "clause.breach"]
    assert len(breach) == 1
    assert breach[0].severity == "warning"
    assert breach[0].source == FINDING_SOURCE_HYBRID
    assert breach[0].location is None
    assert "不完整" in breach[0].message


def test_llm_unmatched_quote_downgrades(monkeypatch):
    """LLM 给的引用在原文找不到 → 降级 + 告警（反幻觉护栏）。"""
    monkeypatch.setattr(
        "app.checkers.clause_checker.chat",
        lambda *a, **k: _llm(
            {"clause_id": "clause.breach", "status": "missing",
             "quote": "这句话原文里根本不存在", "reason": "x"},
        ),
    )
    collector = _run(WEAK_BREACH)
    breach = [f for f in collector.items if f.rule_id == "clause.breach"][0]
    assert breach.severity == "info"  # warning 降级
    assert breach.location is None
    assert any("无法在原文匹配" in w for w in collector.warnings)


def test_non_contract_doc_type_skipped():
    collector = _run(GOOD_CONTRACT, doc_type="general")
    assert collector.items == []
    assert "clause.check" in collector.skipped


def test_malformed_llm_output_warns(monkeypatch):
    """LLM 输出不是 JSON → 两轮都解析失败 → 只告警，不产出结论。"""
    monkeypatch.setattr("app.checkers.clause_checker.chat",
                        lambda *a, **k: SimpleNamespace(content="不是JSON"))
    collector = _run(WEAK_BREACH)
    assert collector.items == []
    assert any("无法解析" in w for w in collector.warnings)


def test_llm_not_configured_warns(monkeypatch):
    def _raise(*a, **k):
        raise LLMNotConfiguredError("no key")

    monkeypatch.setattr("app.checkers.clause_checker.chat", _raise)
    collector = _run(WEAK_BREACH)
    # 未配置 LLM：弱信号与缺失项都不出结论，只告警并按 clause 记 skipped
    assert collector.items == []
    assert any("LLM" in w for w in collector.warnings)
    assert "clause.breach" in collector.skipped
