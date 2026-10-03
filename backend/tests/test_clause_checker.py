"""ClauseChecker 测试：规则预筛、LLM 存疑判定、反幻觉护栏、无包跳过。"""

import json
import uuid
from types import SimpleNamespace

from app.checkers.clause_checker import ClauseChecker
from app.db import storage
from app.llm.client import LLMNotConfiguredError
from app.models.document import Artifact, Document
from app.tasks.review_pipeline import FindingCollector
from conftest import TestSessionLocal
from tests.test_intake import _make_user


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


def test_direct_missing_no_llm(monkeypatch):
    called = []
    monkeypatch.setattr("app.checkers.clause_checker.chat",
                        lambda *a, **k: called.append(1))
    text = GOOD_CONTRACT.replace(
        "第五条 违约责任：任何一方违约，应向守约方支付违约金并赔偿损失。\n", ""
    ).replace(
        "第六条 争议解决：协商不成的，提交仲裁委员会仲裁。\n", ""
    )
    collector = _run(text)
    rule_ids = {f.rule_id for f in collector.items}
    assert rule_ids == {"clause.breach", "clause.dispute"}
    assert all(f.severity == "warning" for f in collector.items)
    assert called == []  # 明确缺失直接出 finding


def test_weak_signal_llm_confirms_missing(monkeypatch):
    payload = json.dumps({"results": [
        {"id": "clause.breach", "present": False, "quote": "",
         "reason": "仅有逾期表述，无违约责任约定"},
    ]}, ensure_ascii=False)
    monkeypatch.setattr("app.checkers.clause_checker.chat",
                        lambda *a, **k: SimpleNamespace(content=payload))
    text = GOOD_CONTRACT.replace(
        "第五条 违约责任：任何一方违约，应向守约方支付违约金并赔偿损失。",
        "第五条 逾期交付的，双方另行协商。",
    ).replace(
        "第六条 争议解决：协商不成的，提交仲裁委员会仲裁。\n", ""
    )
    collector = _run(text)
    breach = [f for f in collector.items if f.rule_id == "clause.breach"]
    assert len(breach) == 1
    assert breach[0].severity == "warning"
    assert breach[0].location is None


def test_llm_unmatched_quote_downgrades(monkeypatch):
    payload = json.dumps({"results": [
        {"id": "clause.breach", "present": False,
         "quote": "这句话原文里根本不存在", "reason": "x"},
    ]}, ensure_ascii=False)
    monkeypatch.setattr("app.checkers.clause_checker.chat",
                        lambda *a, **k: SimpleNamespace(content=payload))
    text = GOOD_CONTRACT.replace(
        "第五条 违约责任：任何一方违约，应向守约方支付违约金并赔偿损失。",
        "第五条 逾期交付的，双方另行协商。",
    ).replace(
        "第六条 争议解决：协商不成的，提交仲裁委员会仲裁。\n", ""
    )
    collector = _run(text)
    breach = [f for f in collector.items if f.rule_id == "clause.breach"][0]
    assert breach.severity == "info"  # warning 降级
    assert breach.location is None
    assert any("无法在原文匹配" in w for w in collector.warnings)


def test_non_contract_doc_type_skipped():
    collector = _run(GOOD_CONTRACT, doc_type="general")
    assert collector.items == []
    assert "clause.check" in collector.skipped


def test_malformed_llm_output_warns(monkeypatch):
    monkeypatch.setattr("app.checkers.clause_checker.chat",
                        lambda *a, **k: SimpleNamespace(content="不是JSON"))
    text = GOOD_CONTRACT.replace(
        "第五条 违约责任：任何一方违约，应向守约方支付违约金并赔偿损失。",
        "第五条 逾期交付的，双方另行协商。",
    ).replace(
        "第六条 争议解决：协商不成的，提交仲裁委员会仲裁。\n", ""
    )
    collector = _run(text)
    # dispute 明确缺失仍会直接出 finding；breach 因输出无法解析不出 finding
    assert {f.rule_id for f in collector.items} == {"clause.dispute"}
    assert any("无法解析" in w for w in collector.warnings)


def test_llm_not_configured_warns(monkeypatch):
    def _raise(*a, **k):
        raise LLMNotConfiguredError("no key")

    monkeypatch.setattr("app.checkers.clause_checker.chat", _raise)
    text = GOOD_CONTRACT.replace(
        "第五条 违约责任：任何一方违约，应向守约方支付违约金并赔偿损失。",
        "第五条 逾期交付的，双方另行协商。",
    ).replace(
        "第六条 争议解决：协商不成的，提交仲裁委员会仲裁。\n", ""
    )
    collector = _run(text)
    # dispute 明确缺失仍直接出 finding；breach 因未配置 LLM 仅告警
    assert {f.rule_id for f in collector.items} == {"clause.dispute"}
    assert any("LLM" in w for w in collector.warnings)
