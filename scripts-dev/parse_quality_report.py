# -*- coding: utf-8 -*-
"""P2-2 解析质量基准集报告（只读：不触发解析、不写库）。

输入：corpus/acceptance_golden/golden_manifest.json 的 40 份真实合同
输出：scripts-dev/parse_quality_report.html + parse_quality_baseline.json
指标：覆盖率、解析成功率、平均字数/页数、表格恢复、OCR 触发率、回退告警；
      与上轮基线（baseline json）对比，展示提升/回退。
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime

from sqlalchemy import text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "corpus", "acceptance_golden", "golden_manifest.json")
OUT_HTML = os.path.join(ROOT, "scripts-dev", "parse_quality_report.html")
OUT_BASE = os.path.join(ROOT, "scripts-dev", "parse_quality_baseline.json")


def load_manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def main():
    manifest = load_manifest()
    doc_ids = manifest["doc_ids"]

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT d.id, d.filename, d.ext, d.doc_type, d.status,
                       dt.status AS task_status, dt.attempts, dt.warnings, dt.stats
                FROM documents d
                LEFT JOIN LATERAL (
                    SELECT status, attempts, warnings, stats
                    FROM document_tasks
                    WHERE document_id = d.id AND task_type = 'parse'
                    ORDER BY created_at DESC LIMIT 1
                ) dt ON true
                WHERE d.id = ANY(:ids)
                """
            ),
            {"ids": doc_ids},
        ).all()
    finally:
        db.close()

    by_id = {str(r[0]): r for r in rows}
    found = 0
    parsed = 0
    ocr_used = 0
    warn_total = 0
    char_total = 0
    page_total = 0
    table_total = 0
    per_doc: list[dict] = []
    status_counter: Counter = Counter()
    ext_counter: Counter = Counter()

    for did in doc_ids:
        r = by_id.get(did)
        if r is None:
            per_doc.append({"doc_id": did, "filename": "(未入库)", "found": False})
            status_counter["未入库"] += 1
            continue
        found += 1
        filename, ext, doc_type, doc_status = r[1], r[2], r[3], r[4]
        task_status = r[5]
        attempts = r[6]
        warnings = r[7] or []
        stats = r[8] or {}
        ext_counter[ext] += 1
        status_counter[doc_status] += 1

        char_count = int(stats.get("char_count") or 0)
        page_count = int(stats.get("page_count") or 0)
        table_count = int(stats.get("table_count") or 0)
        ocr = bool(stats.get("ocr_used"))
        if task_status == "parsed":
            parsed += 1
            char_total += char_count
            page_total += page_count
            table_total += table_count
            if ocr:
                ocr_used += 1
            warn_total += len(warnings)
        per_doc.append({
            "doc_id": did[:8], "filename": filename, "ext": ext,
            "doc_type": doc_type, "doc_status": doc_status,
            "task_status": task_status, "attempts": attempts,
            "char_count": char_count, "page_count": page_count,
            "table_count": table_count, "ocr_used": ocr, "warnings": len(warnings),
            "found": True,
        })

    n = len(doc_ids)
    metrics = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "doc_count": n,
        "found": found,
        "parsed": parsed,
        "ocr_used": ocr_used,
        "warn_total": warn_total,
        "avg_chars": round(char_total / max(parsed, 1)),
        "avg_pages": round(page_total / max(parsed, 1), 1),
        "avg_tables": round(table_total / max(parsed, 1), 1),
        "success_rate": round(parsed / max(found, 1), 4),
        "ocr_rate": round(ocr_used / max(parsed, 1), 4),
        "coverage_rate": round(found / max(n, 1), 4),
    }

    old = {}
    if os.path.exists(OUT_BASE):
        with open(OUT_BASE, encoding="utf-8") as f:
            old = json.load(f)

    def diff(key):
        if key in old and key != "generated_at" and old.get(key) is not None and metrics[key] is not None:
            delta = metrics[key] - old[key]
            return delta
        return None

    # HTML 报告
    rows_html = []
    for d in sorted(per_doc, key=lambda x: (x["filename"] or "")):
        flag = ""
        if not d["found"]:
            flag = '<span class="badge bad">未入库</span>'
        elif d["task_status"] == "parsed":
            flag = '<span class="badge ok">已解析</span>'
        elif d["task_status"] == "failed":
            flag = '<span class="badge bad">失败</span>'
        else:
            flag = f'<span class="badge wait">{d["task_status"] or "未解析"}</span>'
        rows_html.append(
            f"<tr><td>{d['filename']}</td><td>{d['ext']}</td><td>{d['doc_type']}</td>"
            f"<td>{flag}</td><td>{d['char_count']}</td><td>{d['page_count']}</td>"
            f"<td>{d['table_count']}</td><td>{'是' if d['ocr_used'] else '否'}</td>"
            f"<td>{d['warnings']}</td></tr>"
        )

    def metric_card(label, value, base_key):
        delta = diff(base_key)
        if delta is None:
            delta_html = '<span class="dim">基线待定</span>'
        elif delta > 0:
            delta_html = f'<span class="up">↑ {delta:+.2f}</span>'
        elif delta < 0:
            delta_html = f'<span class="down">↓ {delta:+.2f}</span>'
        else:
            delta_html = '<span class="flat">持平</span>'
        return (
            f'<div class="card"><div class="v">{value}</div>'
            f'<div class="l">{label}</div><div class="d">{delta_html}</div></div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>解析质量基准集报告</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;margin:24px;background:#f5f7fa;color:#303133}}
h1{{font-size:20px}} .meta{{color:#909399;font-size:12px;margin-bottom:16px}}
.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:20px}}
.card{{background:#fff;border-radius:10px;padding:14px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.v{{font-size:24px;font-weight:700}} .l{{font-size:12px;color:#909399;margin-top:4px}}
.d{{font-size:12px;margin-top:6px}} .up{{color:#67c23a}} .down{{color:#f56c6c}} .flat{{color:#909399}} .dim{{color:#c0c4cc}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px}}
th,td{{border:1px solid #ebeef5;padding:8px 10px;text-align:left}}
th{{background:#f0f2f5}} .badge{{padding:2px 8px;border-radius:10px;font-size:12px}}
.ok{{background:#f0f9eb;color:#67c23a}} .bad{{background:#fef0f0;color:#f56c6c}}
.wait{{background:#fdf6ec;color:#e6a23c}}
</style></head><body>
<h1>解析质量基准集报告</h1>
<div class="meta">golden 集 v{manifest['version']} · {manifest.get('doc_count')} 份真实合同 · 生成于 {metrics['generated_at']}</div>
<div class="cards">
{metric_card('覆盖率', f"{metrics['coverage_rate']*100:.0f}%", 'coverage_rate')}
{metric_card('解析成功率', f"{metrics['success_rate']*100:.0f}%", 'success_rate')}
{metric_card('平均字数/份', metrics['avg_chars'], 'avg_chars')}
{metric_card('平均页数/份', metrics['avg_pages'], 'avg_pages')}
{metric_card('平均表格/份', metrics['avg_tables'], 'avg_tables')}
{metric_card('OCR 触发率', f"{metrics['ocr_rate']*100:.0f}%", 'ocr_rate')}
</div>
<div class="meta">回退告警累计 {metrics['warn_total']} 条 · 已解析 {metrics['parsed']}/{metrics['found']} · OCR {metrics['ocr_used']} · 分布 {dict(ext_counter)}</div>
<table><tr><th>文件名</th><th>格式</th><th>类型</th><th>状态</th><th>字数</th><th>页数</th><th>表格</th><th>OCR</th><th>告警</th></tr>
{''.join(rows_html)}
</table>
</body></html>"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    with open(OUT_BASE, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("report:", OUT_HTML)


if __name__ == "__main__":
    main()
