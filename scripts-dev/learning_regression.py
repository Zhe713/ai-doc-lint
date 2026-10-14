# -*- coding: utf-8 -*-
"""W7-4 自学习闭环回归验证：
1) 闭环演练：对真实合同 findings 标记误报（模拟用户反馈）→ 触发调优 → 白名单扩充/建议生成；
2) golden 回归对比：调优前 typo 发现数 vs auto 白名单过滤后预估数；
3) 输出 HTML 效果报告（改动/提升/优化 + 回滚说明）。
用法：python scripts-dev/learning_regression.py
"""
import json
import os
import urllib.request
from pathlib import Path

BASE = "http://localhost:8080"
ADMIN = ("boss_admin", "AdminPass123")
OUT_HTML = r"D:\projects\ai-doc-lint\ux-review\w7-learning-regression.html"
OUT_JSON = r"D:\projects\ai-doc-lint\ux-review\w7_learning_regression.json"

MAX_FEEDBACK = 5  # 演示反馈条数


def api(method, path, body=None, token=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def login():
    data = api("POST", "/api/v1/auth/login", {"username": ADMIN[0], "password": ADMIN[1]})
    return data["access_token"]


def main():
    token = login()
    report = {"steps": []}

    # 1) 找一份含 typo findings 的文档，模拟误报反馈
    docs = api("GET", "/api/v1/documents?limit=50", token=token)
    target = None
    for doc in docs:
        f = api("GET", f"/api/v1/documents/{doc['id']}/findings", token=token)
        typo = [it for it in f.get("items", []) if it.get("checker") == "typo"][:MAX_FEEDBACK]
        if typo:
            target = {"doc": doc, "typo": typo}
            break
    if target is None:
        report["steps"].append({"step": "find_typo_docs", "note": "无 typo findings 可用，跳过反馈演练"})
    else:
        words = []
        for it in target["typo"]:
            api("PATCH", f"/api/v1/findings/{it['id']}",
                {"status": "ignored", "feedback_reason": "false_positive"}, token=token)
            msg = it.get("message") or ""
            if "「" in msg:
                words.append(msg.split("「")[1].split("」")[0])
        report["steps"].append({
            "step": "feedback_inject",
            "doc": target["doc"]["filename"],
            "count": len(target["typo"]),
            "words": words,
        })

    # 2) 手动触发调优
    summary = api("POST", "/api/v1/admin/learning/run-tuning", {}, token=token)
    report["tuning"] = summary
    report["steps"].append({"step": "run_tuning", "summary": summary})

    # 3) 采集反馈统计 / 建议 / 日志
    report["feedback"] = api("GET", "/api/v1/admin/learning/feedback", token=token)
    report["suggestions"] = api("GET", "/api/v1/admin/learning/suggestions?status=pending", token=token)
    report["logs"] = api("GET", "/api/v1/admin/learning/logs?limit=20", token=token)

    # 4) golden 回归对比：读 golden 40 份 typo 发现，auto 白名单过滤后预估减少
    auto_path = Path(r"D:\projects\ai-doc-lint\backend\app\checkers\rules\typo_whitelist_auto.txt")
    auto_words = set()
    if auto_path.exists():
        auto_words = {
            ln.strip() for ln in auto_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        }
    golden_dir = Path(r"D:\projects\ai-doc-lint\corpus\acceptance_golden")
    golden_rows = []
    if (golden_dir / "l1_results.json").exists():
        golden_rows = json.loads((golden_dir / "l1_results.json").read_text(encoding="utf-8"))

    golden_typo_before = 0
    golden_typo_after = 0
    affected = set()
    for r in golden_rows:
        doc_id = r.get("doc_id")
        if not doc_id or r.get("status") != "parsed":
            continue
        f = api("GET", f"/api/v1/documents/{doc_id}/findings?checker=typo", token=token)
        items = f.get("items", [])
        before = len(items)
        after = 0
        for it in items:
            wrong = (it.get("message") or "").split("「")[1].split("」")[0] if "「" in (it.get("message") or "") else ""
            if wrong in auto_words:
                affected.add(wrong)
                continue
            after += 1
        golden_typo_before += before
        golden_typo_after += after
    report["regression"] = {
        "golden_checked": len(golden_rows),
        "typo_before": golden_typo_before,
        "typo_after_filter": golden_typo_after,
        "typo_reduced": golden_typo_before - golden_typo_after,
        "auto_whitelist_words": len(auto_words),
        "affected_words": sorted(affected)[:50],
    }

    # 5) 落 JSON
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    Path(OUT_JSON).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6) 生成 HTML 报告
    html = render_html(report, auto_words)
    Path(OUT_HTML).write_text(html, encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "tuning": summary,
        "regression": report["regression"],
        "html": OUT_HTML,
    }, ensure_ascii=False, indent=2))


def render_html(report: dict, auto_words: set[str]) -> str:
    t = report.get("tuning", {})
    reg = report.get("regression", {})
    fb = report.get("feedback", {}).get("items", [])
    sugg = report.get("suggestions", {}).get("items", [])
    logs = report.get("logs", {}).get("items", [])

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    fb_rows = "".join(
        f"<tr><td>{esc(i.get('checker'))}</td><td>{esc(i.get('rule_id'))}</td>"
        f"<td>{i.get('hit_count')}</td><td>{i.get('false_count')}</td>"
        f"<td>{i.get('confirmed_count')}</td><td>{(i.get('false_rate') or 0) * 100:.1f}%</td></tr>"
        for i in fb
    ) or '<tr><td colspan="6">暂无反馈</td></tr>'
    sugg_rows = "".join(
        f"<tr><td>{esc(i.get('checker'))}</td><td>{esc(i.get('rule_id'))}</td>"
        f"<td>{i.get('false_count')}/{i.get('hit_count')}（{i.get('false_rate') * 100:.1f}%）</td>"
        f"<td>{esc(i.get('reason'))}</td><td>待确认</td></tr>"
        for i in sugg
    ) or '<tr><td colspan="5">无待确认建议</td></tr>'
    log_rows = "".join(
        f"<tr><td>{esc(i.get('created_at', '')).replace('T', ' ')[:19]}</td>"
        f"<td>{esc(i.get('action'))}</td><td>{esc(json.dumps(i.get('detail'), ensure_ascii=False))}</td></tr>"
        for i in logs
    ) or '<tr><td colspan="3">暂无日志</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>W7 自学习闭环回归报告</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;margin:0;background:#f5f7fa;color:#303133}}
.wrap{{max-width:960px;margin:0 auto;padding:24px}}
h1{{font-size:22px}}h2{{font-size:16px;margin-top:24px}}
.card{{background:#fff;border-radius:8px;padding:20px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{border:1px solid #e4e7ed;padding:6px 10px;text-align:left}}
th{{background:#f0f2f5}}
.kpi{{display:flex;gap:16px;flex-wrap:wrap}}
.kpi div{{flex:1;min-width:140px;background:#f0f9ff;border-radius:8px;padding:14px;text-align:center}}
.kpi b{{display:block;font-size:24px;color:#1989fa}}
.tag{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#ecf5ff;color:#409eff;margin:2px}}
.ok{{color:#67c23a}} .warn{{color:#e6a23c}} .danger{{color:#f56c6c}}
</style></head><body><div class="wrap">
<h1>W7 自学习闭环回归报告</h1>
<div class="card">
<b>本次调优（{esc(t.get('trigger'))}）</b>：
新增白名单词 <b class="ok">{t.get('whitelist_added', 0)}</b> 个（累计 {t.get('whitelist_total', 0)}），
建议停用规则 <b class="warn">{len(t.get('suggested_rules', []))}</b> 条。
<div class="tag" style="margin-top:8px">回滚方式：删除 rules/typo_whitelist_auto.txt 即可完全回退白名单扩充</div>
</div>
<h2>golden 回归对比（40 份真实合同）</h2>
<div class="card"><div class="kpi">
<div><b>{reg.get('golden_checked', 0)}</b>参与回归文档</div>
<div><b>{reg.get('typo_before', 0)}</b>调优前 typo 发现</div>
<div><b>{reg.get('typo_after_filter', 0)}</b>白名单过滤后预估</div>
<div><b class="ok">-{reg.get('typo_reduced', 0)}</b>预计减少误报</div>
</div>
<div style="margin-top:12px">受影响词（进入白名单后不再报）：{''.join(f'<span class="tag">{esc(w)}</span>' for w in reg.get('affected_words', [])[:30]) or '（无）'}</div>
</div>
<h2>反馈统计</h2>
<div class="card"><table><tr><th>检查器</th><th>规则</th><th>命中</th><th>误报</th><th>确认</th><th>误报率</th></tr>{fb_rows}</table></div>
<h2>停用建议（待确认）</h2>
<div class="card"><table><tr><th>检查器</th><th>规则</th><th>误报情况</th><th>原因</th><th>状态</th></tr>{sugg_rows}</table></div>
<h2>学习日志</h2>
<div class="card"><table><tr><th>时间</th><th>动作</th><th>详情</th></tr>{log_rows}</table></div>
</div></body></html>"""


if __name__ == "__main__":
    main()
