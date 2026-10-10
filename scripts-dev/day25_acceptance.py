"""W5 Day25 真实合同验收：全部使用网络公开真实合同（语料见 corpus/manifest.csv）。

三类验收：
A. 中文真实合同（ccgp 政府采购合同公告 ×4）文档内勾稽：规则抽取 + CrossChecker
   ——预期：3 份单价×数量=总价一致不报；始兴县明德中学 1 份单价×数量≠总价（真实差异）报 error
B. 英文真实合同（CUAD ×10，LLM 补抽字段）文档内勾稽：验证不崩、不误报、字段命中率
C. 跨文档比对（ccgp ×4 组成比对组）：CrossDocChecker 两两勾稽——当事人不一致/金额差异

统计输出 JSON 到 /tmp/day25_report.json，同时打印摘要。
"""

import json
import sys
import uuid
from pathlib import Path

from app.db import storage
from app.db.session import SessionLocal
from app.models.document import (
    STATUS_PARSED,
    Artifact,
    Document,
    DocumentField,
    DocumentTask,
)
from app.tasks.review_pipeline import FindingCollector, summarize

CORPUS = Path("/tmp/corpus")
CCGP = sorted((CORPUS / "ccgp").glob("*.txt"))
CUAD_SAMPLE = sorted((CORPUS / "cuad").glob("*.txt"))[:10]


def _make_doc(db, user, filename: str, text: str) -> Document:
    doc = Document(
        user_id=user.id, filename=filename,
        storage_key=f"docs/{user.id}/orig_{uuid.uuid4().hex}.txt",
        sha256=uuid.uuid4().hex, size_bytes=len(text.encode("utf-8")),
        content_type="text/plain", ext="txt", doc_type="contract",
        status=STATUS_PARSED,
    )
    db.add(doc)
    db.flush()
    key = f"artifacts/{doc.id}/plaintext.txt"
    storage.put_object(key, text.encode("utf-8"), content_type="text/plain")
    db.add(Artifact(document_id=doc.id, kind="plaintext", storage_key=key))
    db.commit()
    return doc


def _field_stats(db, doc) -> dict:
    rows = db.query(DocumentField).filter(DocumentField.document_id == doc.id).all()
    return {f.field_key: {
        "value_text": (f.value_text or "")[:40],
        "value_number": f.value_number,
        "value_date": f.value_date.isoformat() if f.value_date else None,
        "source": f.source,
    } for f in rows}


def _new_task(db, doc, user, task_type="review") -> DocumentTask:
    task = DocumentTask(
        document_id=doc.id, user_id=user.id, task_type=task_type,
        status=STATUS_PARSED, max_attempts=1,
        stats={"checks": ["cross"]},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def run_doc_intra(db, user, path: Path, *, allow_llm: bool) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    doc = _make_doc(db, user, f"day25_{path.name}", text)

    from app.extract.field_extractor import FieldExtractor

    extractor = FieldExtractor(db, doc, allow_llm=allow_llm)
    fields = extractor.run()
    db.commit()

    task = _new_task(db, doc, user)
    collector = FindingCollector(db, task)
    from app.checkers.cross_checker import CrossChecker

    CrossChecker(db, doc, collector).run()
    collector.flush()
    db.commit()

    return {
        "file": path.name,
        "allow_llm": allow_llm,
        "llm_calls": extractor.llm_calls if hasattr(extractor, "llm_calls") else None,
        "fields": _field_stats(db, doc),
        "field_count": len(fields),
        "findings": [
            {"rule_id": f.rule_id, "severity": f.severity, "message": f.message}
            for f in collector.items
        ],
        "summary": summarize(collector.items, collector.skipped, collector.warnings),
        "doc_id": str(doc.id),
    }


def run_cross_doc(db, user, paths: list[Path]) -> dict:
    texts = [p.read_text(encoding="utf-8", errors="ignore") for p in paths]
    docs = [_make_doc(db, user, f"day25_group_{p.name}", t) for p, t in zip(paths, texts)]

    from app.extract.field_extractor import FieldExtractor

    fields_by_doc = {}
    for d in docs:
        FieldExtractor(db, d, allow_llm=False).run()
        db.commit()
        rows = db.query(DocumentField).filter(DocumentField.document_id == d.id).all()
        fields_by_doc[str(d.id)] = {f.field_key: f for f in rows}

    task = _new_task(db, docs[0], user, task_type="cross_compare")
    collector = FindingCollector(db, task)
    from app.checkers.cross_doc_checker import CrossDocChecker

    CrossDocChecker(collector, docs, fields_by_doc).run()
    collector.flush()
    db.commit()

    return {
        "group": [p.name for p in paths],
        "fields_by_doc": {
            d.filename: {k: (v.value_text or "")[:30] for k, v in fd.items()}
            for d, fd in zip(docs, [fields_by_doc[str(d.id)] for d in docs])
        },
        "findings": [
            {"rule_id": f.rule_id, "severity": f.severity, "message": f.message,
             "related": f.related_document_id is not None}
            for f in collector.items
        ],
        "summary": summarize(collector.items, collector.skipped, collector.warnings),
    }


def main() -> None:
    db = SessionLocal()
    from app.models.user import User

    user = db.query(User).filter(User.username == "boss_admin").one()
    report: dict = {}

    # A. 中文真实合同：ccgp ×4
    report["intra_zh"] = [
        run_doc_intra(db, user, p, allow_llm=False) for p in CCGP
    ]

    # B. 英文真实合同：CUAD ×10（LLM 补抽）
    report["intra_en"] = [
        run_doc_intra(db, user, p, allow_llm=True) for p in CUAD_SAMPLE
    ]

    # C. 跨文档比对：ccgp ×4 组成比对组
    report["cross_doc"] = run_cross_doc(db, user, CCGP)

    out = Path("/tmp/day25_report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print("report written:", out)

    # ---- 摘要 ----
    print("\n===== A. 中文合同文档内勾稽 (ccgp ×4) =====")
    for r in report["intra_zh"]:
        f = r["findings"]
        print(f"- {r['file'][:30]}: fields={r['field_count']} "
              f"findings={len(f)} " +
              ("; ".join(f"{x['rule_id']}({x['severity']})" for x in f) or "无"))

    print("\n===== B. 英文合同文档内勾稽 (CUAD ×10, LLM 补抽) =====")
    hit = sum(1 for r in report["intra_en"] if r["field_count"] > 0)
    tot_f = sum(len(r["findings"]) for r in report["intra_en"])
    print(f"抽到字段的文档: {hit}/10, 总 findings: {tot_f}")
    for r in report["intra_en"]:
        print(f"- {r['file'][:40]}: fields={r['field_count']} findings={len(r['findings'])}")

    print("\n===== C. 跨文档比对 (ccgp ×4 一组) =====")
    s = report["cross_doc"]["summary"]
    print(f"findings={s['total']} by_severity={s['by_severity']}")
    for f in report["cross_doc"]["findings"][:8]:
        print(f"- {f['rule_id']}({f['severity']}): {f['message'][:70]}")

    db.close()


if __name__ == "__main__":
    main()
