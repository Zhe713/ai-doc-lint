# -*- coding: utf-8 -*-
"""注入错误评测：把 corpus/injected_errors 跑一遍完整流水线，用人工真值算精确率/召回率/F1。

与 golden_f1.py 的区别：
- golden_f1 用真实合同的「近似真值」做回归，回答"整体表现如何"；
- 本脚本用人工注入的「精确真值」，回答"埋进去的错误到底查出来没有"，可逐条对账。

流程：登录 → 清理同名历史文档 → 逐份上传 → 等 review 终态 → 拉 findings
     → 与 ground_truth.json 逐条匹配（rule_id + 关键词）→ 输出 JSON + HTML。

用法（容器内，能直连 API 与数据库）：
  python scripts-dev/eval_injected.py --api http://localhost:8000
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "corpus", "injected_errors")
GT_PATH = os.path.join(CORPUS, "ground_truth.json")
OUT_JSON = os.path.join(ROOT, "scripts-dev", "injected_eval_result.json")
OUT_HTML = os.path.join(ROOT, "scripts-dev", "injected_eval_report.html")

TERMINAL = {"parsed", "failed", "cancelled", "awaiting_decision"}


# ------------------------------------------------------------------ HTTP

def _req(api: str, method: str, path: str, token: str | None = None,
         body: dict | None = None) -> tuple[int, dict | list | None]:
    url = f"{api}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"detail": raw.decode("utf-8", "ignore")[:300]}


def _upload(api: str, token: str, path: str,
            checks: str = "format,typo,clause,cross",
            doc_type: str = "contract") -> tuple[int, dict]:
    """multipart 上传单个文件（标准库实现，避免额外依赖）。

    checks 必须显式给出：不传时后端走 DEFAULT_CHECKS（只有 format+typo），
    条款与勾稽检查根本不会执行，评测会误判成「漏检」。
    """
    boundary = "----injeval" + str(int(time.time() * 1000))
    name = os.path.basename(path)
    with open(path, "rb") as f:
        content = f.read()
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="files"; filename="{name}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        content,
        f"\r\n--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="checks"\r\n\r\n',
        checks.encode(),
        f"\r\n--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="doc_type"\r\n\r\n',
        doc_type.encode(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(
        f"{api}/api/v1/documents/upload", data=body, method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"detail": raw.decode("utf-8", "ignore")[:300]}


# ------------------------------------------------------------------ DB

def _cleanup(db, filenames: list[str]) -> int:
    from sqlalchemy import text

    n = 0
    for fn in filenames:
        rows = db.execute(
            text("SELECT id FROM documents WHERE filename = :fn"), {"fn": fn}
        ).fetchall()
        for (doc_id,) in rows:
            for tbl in ("check_findings", "document_tasks", "document_fields",
                        "artifacts", "document_chunks"):
                db.execute(text(f"DELETE FROM {tbl} WHERE document_id = :d"), {"d": doc_id})
            db.execute(text("DELETE FROM documents WHERE id = :d"), {"d": doc_id})
            n += 1
    db.commit()
    return n


def _wait_review(db, doc_id: str, timeout: float = 420.0) -> str:
    """等该文档的 review 任务进入终态，返回最终状态。"""
    from sqlalchemy import text

    deadline = time.time() + timeout
    last = "?"
    while time.time() < deadline:
        row = db.execute(
            text(
                "SELECT status FROM document_tasks "
                "WHERE document_id = :d AND task_type = 'review' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"d": doc_id},
        ).fetchone()
        if row is None:
            # 解析还没结束、review 尚未创建
            prow = db.execute(
                text(
                    "SELECT status FROM document_tasks "
                    "WHERE document_id = :d AND task_type = 'parse' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"d": doc_id},
            ).fetchone()
            last = f"parse:{prow[0]}" if prow else "none"
            if prow and prow[0] in ("failed", "awaiting_decision", "cancelled"):
                return prow[0]
        elif row[0] in TERMINAL:
            return row[0]
        else:
            last = row[0]
        db.commit()  # 结束只读事务，看到最新提交
        time.sleep(3)
    return f"timeout({last})"


def _findings(db, doc_id: str) -> list[dict]:
    from sqlalchemy import text

    rows = db.execute(
        text(
            "SELECT rule_id, checker, severity, message, source, llm_reason "
            "FROM check_findings WHERE document_id = :d ORDER BY id"
        ),
        {"d": doc_id},
    ).fetchall()
    return [
        {"rule_id": r[0], "checker": r[1], "severity": r[2], "message": r[3] or "",
         "source": r[4] or "rule", "llm_reason": r[5]}
        for r in rows
    ]


# ------------------------------------------------------------------ 匹配

def _expected_ids(exp: dict) -> list[str]:
    ids = []
    if exp.get("rule_id"):
        ids.append(exp["rule_id"])
    for extra in exp.get("also_rule_ids") or []:
        if extra:
            ids.append(extra)
    return ids


def _matches(exp: dict, f: dict) -> bool:
    """一条 finding 是否算「命中了这条注入错误」。

    匹配口径（任一成立即可）：
    1) rule_id 命中（含 also_rule_ids 声明的等价规则）；
    2) message 含 keyword（应对自定义规则包改名把 rule_id 变成 custom_N 的情况）；
    3) message 含 also_keywords（应对同一处错误被另一个检查器用不同规则报出的情况）。
    """
    if f["rule_id"] in _expected_ids(exp):
        return True
    msg = f["message"] or ""
    kw = exp.get("keyword")
    if kw and kw in msg:
        return True
    return any(k and k in msg for k in (exp.get("also_keywords") or []))


def match(expected: list[dict], got: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """匹配注入错误与 findings，返回 (命中, 漏报, 误报)。

    与贪心一一配对不同：这里先判断「每条 finding 能否被任何一条真值解释」，
    再多对一收集命中。理由是同一处错误可能被多个检查器同时报出
    （如金额大小写不一致：cross 报勾稽、clause 报金额条款），两条都正确，
    不应该把第二条算成误报。
    """
    explained = [False] * len(got)
    hits, misses = [], []
    for exp in expected:
        found = []
        for j, f in enumerate(got):
            if _matches(exp, f):
                explained[j] = True
                found.append(j)
        if found:
            hits.append({**exp, "found": got[found[0]],
                         "all": [got[j] for j in found]})
        else:
            misses.append(exp)
    fps = [f for j, f in enumerate(got) if not explained[j]]
    return hits, misses, fps


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / max(tp + fp, 1)
    r = tp / max(tp + fn, 1)
    f1 = 2 * p * r / max(p + r, 1e-9)
    return round(p, 4), round(r, 4), round(f1, 4)


# ------------------------------------------------------------------ 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--user", default=os.environ.get("EVAL_USER", "boss_admin"))
    ap.add_argument("--password", default=os.environ.get("EVAL_PASSWORD", "AdminPass123"))
    ap.add_argument("--timeout", type=float, default=420.0)
    ap.add_argument("--keep", action="store_true", help="不清理历史文档")
    ap.add_argument("--only", default="", help="只跑文件名含该子串的用例（调试单份用）")
    args = ap.parse_args()

    gt = json.loads(open(GT_PATH, encoding="utf-8").read())
    files = gt["files"]
    if args.only:
        files = [g for g in files if args.only in g["file"]]
        if not files:
            print(f"没有匹配 --only {args.only} 的用例", file=sys.stderr)
            return 2

    from app.db.session import SessionLocal

    db = SessionLocal()

    code, payload = _req(args.api, "POST", "/api/v1/auth/login",
                         body={"username": args.user, "password": args.password})
    if code != 200:
        print(f"登录失败 {code}: {payload}", file=sys.stderr)
        return 2
    token = payload["access_token"]

    if not args.keep:
        n = _cleanup(db, [g["file"] for g in files])
        print(f"清理历史同文档 {n} 份")

    results = []
    for g in files:
        path = os.path.join(CORPUS, g["file"])
        t0 = time.time()
        code, resp = _upload(args.api, token, path)
        if code not in (200, 201):
            print(f"[上传失败] {g['file']} {code} {resp}")
            results.append({"file": g["file"], "error": f"upload {code}: {resp}"})
            continue
        doc_id = resp["tasks"][0]["document_id"]
        state = _wait_review(db, doc_id, args.timeout)
        got = _findings(db, doc_id)
        hits, misses, fps = match(g["expect"], got)
        results.append({
            "file": g["file"], "desc": g["desc"], "doc_id": doc_id,
            "state": state, "elapsed": round(time.time() - t0, 1),
            "expected": len(g["expect"]), "hit": len(hits), "miss": len(misses),
            "fp": len(fps), "findings": len(got),
            "hits": [{"note": h.get("note"), "type": h.get("type"),
                      "rule_id": h.get("rule_id"),
                      "source": h["found"]["source"],
                      "llm_reason": h["found"]["llm_reason"],
                      "message": h["found"]["message"]} for h in hits],
            "misses": [{"note": m.get("note"), "rule_id": m.get("rule_id"),
                        "keyword": m.get("keyword")} for m in misses],
            "fps": [{"rule_id": f["rule_id"], "message": f["message"]} for f in fps],
            "sources": {s: sum(1 for f in got if f["source"] == s)
                        for s in ("rule", "hybrid", "llm")},
        })
        print(f"{g['file']:30s} {state:12s} 命中 {len(hits)}/{len(g['expect'])} "
              f"误报 {len(fps)}  {round(time.time() - t0, 1)}s")

    db.close()

    # ---- 汇总 ----
    exp_total = sum(r.get("expected", 0) for r in results)
    tp = sum(r.get("hit", 0) for r in results)
    fn = sum(r.get("miss", 0) for r in results)
    fp = sum(r.get("fp", 0) for r in results)
    p, r_, f1 = prf(tp, fp, fn)

    by_type: dict[str, dict] = {}
    for g, res in zip(files, results):
        for exp in g["expect"]:
            t = exp["type"]
            by_type.setdefault(t, {"expected": 0, "hit": 0, "fp": 0})
            by_type[t]["expected"] += 1
        for h in res.get("hits", []):
            t = h.get("type") or "other"
            by_type.setdefault(t, {"expected": 0, "hit": 0, "fp": 0})["hit"] += 1
        for f in res.get("fps", []):
            t = {"typo": "typo", "clause": "clause", "cross": "cross",
                 "format": "format"}.get(f["rule_id"].split(".")[0], "other")
            by_type.setdefault(t, {"expected": 0, "hit": 0, "fp": 0})["fp"] += 1

    for t, c in by_type.items():
        # expected=0 的类型（通常是归类失败的 other）不算召回，避免出现 12.0 这种比值
        c["recall"] = round(c["hit"] / c["expected"], 4) if c["expected"] else 0.0
        c["precision"] = round(c["hit"] / max(c["hit"] + c["fp"], 1), 4)
        c["f1"] = prf(c["hit"], c["fp"], max(c["expected"] - c["hit"], 0))[2]

    src_total = {s: sum(x.get("sources", {}).get(s, 0) for x in results)
                 for s in ("rule", "hybrid", "llm")}

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "files": len(files), "expected_total": exp_total,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": p, "recall": r_, "f1": f1,
        "by_type": by_type, "sources": src_total,
        "details": results,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ---- HTML ----
    def row(res: dict) -> str:
        marks = "".join(
            f'<span class="pill ok">{html.escape(h["note"] or h["rule_id"])}'
            f'<i>{h["source"]}</i></span>' for h in res.get("hits", [])
        ) + "".join(
            f'<span class="pill miss">{html.escape(m["note"] or m["rule_id"])}</span>'
            for m in res.get("misses", [])
        ) + "".join(
            f'<span class="pill fp">{html.escape(f["message"][:40])}</span>'
            for f in res.get("fps", [])
        )
        return (f"<tr><td>{html.escape(res['file'])}<div class='sub'>"
                f"{html.escape(res.get('desc') or '')}</div></td>"
                f"<td>{res.get('state', '-')}</td>"
                f"<td>{res.get('hit', 0)}/{res.get('expected', 0)}</td>"
                f"<td>{res.get('fp', 0)}</td><td>{res.get('elapsed', '-')}s</td>"
                f"<td class='marks'>{marks or '<span class=dim>—</span>'}</td></tr>")

    trows = "".join(
        f"<tr><td>{t}</td><td>{c['expected']}</td><td>{c['hit']}</td>"
        f"<td>{c['fp']}</td><td>{c['recall']:.2f}</td>"
        f"<td>{c['precision']:.2f}</td><td><b>{c['f1']:.2f}</b></td></tr>"
        for t, c in sorted(by_type.items())
    )

    html_doc = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>注入错误评测报告</title><style>
body{{font-family:'Microsoft YaHei',sans-serif;margin:24px;background:#f5f7fa;color:#303133}}
h1{{font-size:20px;margin-bottom:4px}} .meta{{color:#909399;font-size:12px;margin-bottom:16px}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}}
.card{{background:#fff;border-radius:10px;padding:14px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.v{{font-size:24px;font-weight:700}} .l{{font-size:12px;color:#909399;margin-top:4px}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px;margin-bottom:16px}}
th,td{{border:1px solid #ebeef5;padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:#f0f2f5}} .sub{{color:#909399;font-size:11px;margin-top:2px}}
.pill{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;margin:2px 4px 2px 0}}
.pill.ok{{background:#f0f9eb;color:#529b2e}} .pill.miss{{background:#fef0f0;color:#c45656}}
.pill.fp{{background:#fdf6ec;color:#b88230}}
.pill i{{font-style:normal;opacity:.65;margin-left:4px}}
.dim{{color:#c0c4cc}}
.note{{background:#fdf6ec;border-left:4px solid #e6a23c;padding:10px 14px;border-radius:6px;
font-size:12px;color:#b88230;margin-bottom:16px;line-height:1.7}}
</style></head><body>
<h1>注入错误评测：埋进去的错误查出来了没有</h1>
<div class="meta">{summary['files']} 份合同 · {exp_total} 条人工注入错误 ·
生成于 {summary['generated_at']} · 真值 corpus/injected_errors/ground_truth.json</div>
<div class="note">与 acceptance_golden 的区别：那边是真实合同的近似真值（回归用），这里是人工埋错、真值逐条精确。
每份文件的命中/漏报/误报在下方逐条列出，可点开对应报告页核对。source 标记该条由 <b>rule</b>（规则）/
<b>hybrid</b>（规则候选+AI 复核）/ <b>llm</b>（AI 语义判定）产生。</div>
<div class="cards">
<div class="card"><div class="v">{tp}/{exp_total}</div><div class="l">命中（TP）</div></div>
<div class="card"><div class="v">{fn}</div><div class="l">漏报（FN）</div></div>
<div class="card"><div class="v">{fp}</div><div class="l">误报（FP）</div></div>
<div class="card"><div class="v">{p:.2f}</div><div class="l">精确率</div></div>
<div class="card"><div class="v">{f1:.2f}</div><div class="l">F1（召回率 {r_:.2f}）</div></div>
</div>
<h3>按错误类型</h3>
<table><tr><th>类型</th><th>注入数</th><th>命中</th><th>误报</th><th>召回率</th><th>精确率</th><th>F1</th></tr>
{trows}</table>
<h3>逐份明细</h3>
<table><tr><th>文件</th><th>终态</th><th>命中</th><th>误报</th><th>耗时</th><th>逐条对账</th></tr>
{''.join(row(x) for x in results)}</table>
<h3>判定来源分布</h3>
<div class="meta">纯规则 {src_total['rule']} 条 · 规则+AI 复核 {src_total['hybrid']} 条 · AI 语义判定 {src_total['llm']} 条</div>
</body></html>"""
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_doc)

    print(json.dumps({k: v for k, v in summary.items() if k != "details"},
                     ensure_ascii=False, indent=2))
    print("report:", OUT_HTML)
    return 0


if __name__ == "__main__":
    sys.exit(main())
