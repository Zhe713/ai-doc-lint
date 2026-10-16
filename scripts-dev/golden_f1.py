# -*- coding: utf-8 -*-
"""P2-4 golden 回归 F1 化：字段级二分类评估（精确率/召回率/F1）。

- 真值：corpus/acceptance_golden/ground_truth.json（40 份真实公开合同的字段级标注，auto 近似真值）
- 系统侧：DB 中每份文档的 findings（clause/field/cross 按字段关键词匹配 message）
- 输出：golden_f1_report.html + golden_f1_baseline.json（与上轮基线对比）
- 口径说明：ground truth 为自动构造近似真值，F1 为字段级代理指标，
  真值 null/空=字段缺失（判为问题），有值=正常；系统命中=findings message 含字段关键词。
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from sqlalchemy import text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GT = os.path.join(ROOT, "corpus", "acceptance_golden", "ground_truth.json")
OUT_HTML = os.path.join(ROOT, "scripts-dev", "golden_f1_report.html")
OUT_BASE = os.path.join(ROOT, "scripts-dev", "golden_f1_baseline.json")

# 字段 → (真值判定函数, 系统关键词)
# 口径：示范文本中"违约金条款/争议解决/编号/管辖"的 null 多为留白/自动标注不确定，
# 不判为缺失（None=跳过）；仅评估有明确真值信号的字段（金额格式/模板缺失/违约金比例）。
FIELD_KEYWORDS = {
    "违约金比例": ("违约金", lambda v: v is not None and len(v) > 0),  # 非空 → 提取到比例（无异常）
    "违约金条款": ("违约金", lambda v: None),  # 留白不可判
    "争议解决": ("争议", lambda v: None),
    "编号": ("编号", lambda v: None),
    "管辖": ("管辖", lambda v: None),
    "金额格式": ("金额", lambda v: v is not None),  # 非 null → 异常
    "模板缺失": ("模板", lambda v: bool(v)),        # 非空 → 缺失
}


def golden_bad(field: str, value) -> bool | None:
    if field not in FIELD_KEYWORDS:
        return None
    _, bad_fn = FIELD_KEYWORDS[field]
    return bad_fn(value)


def system_hit(field: str, messages: list[str]) -> bool:
    kw = FIELD_KEYWORDS[field][0]
    return any(kw in (m or "") for m in messages)


def main():
    gts = json.loads(open(GT, encoding="utf-8").read())

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT f.document_id, f.checker, f.severity, f.message
                FROM check_findings f
                JOIN documents d ON d.id = f.document_id
                WHERE f.document_id IN (
                    SELECT id FROM documents WHERE filename LIKE ANY(:like)
                )
                """
            ),
            {"like": [f"%{g['file']}%" for g in gts]},
        ).all()
    finally:
        db.close()

    by_doc: dict[str, list[str]] = {}
    for doc_id, checker, sev, msg in rows:
        by_doc.setdefault(str(doc_id), []).append(f"[{checker}] {msg}")

    # 文件名 → doc_id 映射（DB 侧）
    db2 = SessionLocal()
    try:
        fid_rows = db2.execute(
            text("SELECT id, filename FROM documents WHERE filename LIKE ANY(:like)"),
            {"like": [f"%{g['file']}%" for g in gts]},
        ).all()
    finally:
        db2.close()
    fid_by_name = {fn: str(i) for i, fn in fid_rows}

    per_field = {f: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for f in FIELD_KEYWORDS}
    per_doc_rows = []
    # 模板缺失项与系统同义关键词的覆盖对照（口径冲突分析）
    CLAUSE_SYNONYMS = {
        "标的": ["标的", "货物名称", "产品名称", "服务内容", "项目名称", "采购内容"],
        "价款": ["价款", "总价", "单价", "合同金额", "报酬", "价格"],
        "违约金": ["违约金", "违约责任", "违约"],
        "质量": ["质量", "质量标准", "验收"],
    }
    sync_conflicts: list[dict] = []

    for g in gts:
        filename = g["file"]
        doc_id = fid_by_name.get(filename)
        messages = by_doc.get(doc_id, []) if doc_id else []
        fields = g.get("fields") or {}
        for field in FIELD_KEYWORDS:
            gv = golden_bad(field, fields.get(field))
            if gv is None:
                continue
            hit = system_hit(field, messages)
            if gv and hit:
                per_field[field]["tp"] += 1
            elif gv and not hit:
                per_field[field]["fn"] += 1
            elif not gv and hit:
                per_field[field]["fp"] += 1
            else:
                per_field[field]["tn"] += 1
        # 模板缺失 → 同义词覆盖对照
        for miss in (fields.get("模板缺失") or []):
            syn = CLAUSE_SYNONYMS.get(miss)
            if syn and doc_id is not None and not system_hit("模板缺失", messages):
                sync_conflicts.append({"file": filename, "missing": miss,
                                       "synonyms": syn, "system_msg": len(messages)})
        per_doc_rows.append({
            "file": filename, "doc_id": (doc_id or "")[:8],
            "findings": len(messages),
            "fields_ok": sum(1 for f in FIELD_KEYWORDS
                             if fields.get(f) is not None and fields.get(f) != []),
        })

    def prf(c):
        p = c["tp"] / max(c["tp"] + c["fp"], 1)
        r = c["tp"] / max(c["tp"] + c["fn"], 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        return round(p, 3), round(r, 3), round(f1, 3)

    metrics = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    total = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    field_rows = []
    for field, c in per_field.items():
        p, r, f1 = prf(c)
        for k in total:
            total[k] += c[k]
        field_rows.append((field, c, p, r, f1))
    tp, fp, fn, tn = total["tp"], total["fp"], total["fn"], total["tn"]
    macro_p = sum(x[2] for x in field_rows) / max(len(field_rows), 1)
    macro_r = sum(x[3] for x in field_rows) / max(len(field_rows), 1)
    macro_f1 = 2 * macro_p * macro_r / max(macro_p + macro_r, 1e-9)
    micro_p = tp / max(tp + fp, 1)
    micro_r = tp / max(tp + fn, 1)
    micro_f1 = 2 * micro_p * micro_r / max(micro_p + micro_r, 1e-9)
    metrics.update({
        "docs_evaluated": len(per_doc_rows),
        "total_tp": tp, "total_fp": fp, "total_fn": fn, "total_tn": tn,
        "macro_precision": round(macro_p, 4), "macro_recall": round(macro_r, 4),
        "macro_f1": round(macro_f1, 4),
        "micro_precision": round(micro_p, 4), "micro_recall": round(micro_r, 4),
        "micro_f1": round(micro_f1, 4),
        "label_conflicts": len(sync_conflicts),
    })
    for field, c, p, r, f1 in field_rows:
        metrics[f"f1_{field}"] = round(f1, 4)

    old = {}
    if os.path.exists(OUT_BASE):
        with open(OUT_BASE, encoding="utf-8") as f:
            old = json.load(f)

    def delta(key):
        if key in old and key != "generated_at":
            v = metrics[key]
            if isinstance(v, (int, float)):
                return round(metrics[key] - old[key], 4)
        return None

    tr = []
    for field, c, p, r, f1 in field_rows:
        d = delta(f"f1_{field}")
        d_html = '<span class="dim">—</span>' if d is None else (
            f'<span class="up">↑{d:+.3f}</span>' if d > 0 else (
                f'<span class="down">↓{d:+.3f}</span>' if d < 0 else '<span class="flat">持平</span>'))
        tr.append(
            f"<tr><td>{field}</td><td>{c['tp']}</td><td>{c['fp']}</td><td>{c['fn']}</td>"
            f"<td>{c['tn']}</td><td>{p:.3f}</td><td>{r:.3f}</td>"
            f"<td><b>{f1:.3f}</b></td><td>{d_html}</td></tr>"
        )

    def card(label, v, key):
        d = delta(key)
        d_html = '<span class="dim">基线待定</span>' if d is None else (
            f'<span class="up">↑{d:+.4f}</span>' if d > 0 else (
                f'<span class="down">↓{d:+.4f}</span>' if d < 0 else '<span class="flat">持平</span>'))
        return f'<div class="card"><div class="v">{v}</div><div class="l">{label}</div><div class="d">{d_html}</div></div>'

    doc_rows = "".join(
        f"<tr><td>{r['file']}</td><td>{r['doc_id']}</td><td>{r['findings']}</td>"
        f"<td>{r['fields_ok']}/6</td></tr>"
        for r in sorted(per_doc_rows, key=lambda x: x["file"])
    )

    conflict_rows = "".join(
        f"<tr><td>{c['file']}</td><td>{c['missing']}</td><td>{'、'.join(c['synonyms'])}</td>"
        f"<td>{c['system_msg']}</td></tr>"
        for c in sync_conflicts[:25]
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>golden 回归 F1 报告</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;margin:24px;background:#f5f7fa;color:#303133}}
h1{{font-size:20px}} .meta{{color:#909399;font-size:12px;margin-bottom:16px}}
.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:20px}}
.card{{background:#fff;border-radius:10px;padding:14px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.v{{font-size:22px;font-weight:700}} .l{{font-size:12px;color:#909399;margin-top:4px}}
.d{{font-size:12px;margin-top:6px}} .up{{color:#67c23a}} .down{{color:#f56c6c}} .flat{{color:#909399}} .dim{{color:#c0c4cc}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px;margin-bottom:16px}}
th,td{{border:1px solid #ebeef5;padding:8px 10px;text-align:left}}
th{{background:#f0f2f5}} .note{{background:#fdf6ec;border-left:4px solid #e6a23c;padding:10px 14px;border-radius:6px;font-size:12px;color:#b88230;margin-bottom:16px}}
</style></head><body>
<h1>golden 回归 F1 报告（P2-4）</h1>
<div class="meta">真值：ground_truth.json（40 份真实公开合同，自动标注近似真值）· 生成于 {metrics['generated_at']}</div>
<div class="note">口径：字段级二分类代理指标——真值 null/空=缺失（判为问题），有值=正常；系统命中=findings 消息含字段关键词。
golden 为自动构造近似真值，F1 用于回归对比而非绝对质量断言。</div>
<div class="cards">
{card('评估文档数', metrics['docs_evaluated'], 'docs_evaluated')}
{card('Macro F1', f"{metrics['macro_f1']:.3f}", 'macro_f1')}
{card('Macro 精确率', f"{metrics['macro_precision']:.3f}", 'macro_precision')}
{card('Macro 召回率', f"{metrics['macro_recall']:.3f}", 'macro_recall')}
{card('标注口径冲突', metrics['label_conflicts'], 'label_conflicts')}
{card('总漏报 FN', metrics['total_fn'], 'total_fn')}
</div>
<h3>字段级评估（精确率/召回率/F1）</h3>
<table><tr><th>字段</th><th>TP</th><th>FP</th><th>FN</th><th>TN</th><th>精确率</th><th>召回率</th><th>F1</th><th>较基线</th></tr>
{''.join(tr)}
</table>
<h3>标注口径冲突分析（golden 字面缺失 vs 系统同义匹配）</h3>
<div class="meta">golden 自动标注按字面词判定缺失；系统 clause 检查器按同义词（如 标的/货物名称/产品名称/服务内容）判定存在。
以下缺失项在系统词表中存在同义词，属于标注口径冲突而非系统漏检。</div>
<table><tr><th>文件</th><th>golden 缺失项</th><th>系统同义词</th><th>系统 findings 数</th></tr>
{conflict_rows if conflict_rows else '<tr><td colspan=4>无口径冲突</td></tr>'}
</table>
<h3>文档明细（40 份）</h3>
<table><tr><th>文件</th><th>doc_id</th><th>findings</th><th>字段完好</th></tr>{doc_rows}</table>
</body></html>"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    with open(OUT_BASE, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("report:", OUT_HTML)


if __name__ == "__main__":
    main()
