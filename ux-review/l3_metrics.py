# -*- coding: utf-8 -*-
"""L3 业务价值代理指标：直查 PostgreSQL 汇总三个核心指标 + 明细分布。
输出：探查打印（stdout）+ l3_business_metrics.json + 指标报告 HTML。
"""
import json
import subprocess

BASE = r"D:\projects\ai-doc-lint"
JSON_OUT = BASE + r"\ux-review\l3_business_metrics.json"


def q(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", "ai-doc-lint-db-1", "psql", "-U", "aidoc", "-d", "ai_doc_lint",
         "-t", "-A", "-F", "|", "-c", sql],
        capture_output=True, encoding="utf-8", timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError("psql failed: " + r.stderr)
    return r.stdout.strip()


def rows(sql: str) -> list:
    out = q(sql)
    if not out:
        return []
    return [line.split("|") for line in out.splitlines() if line.strip()]


def count(sql: str) -> int:
    out = q(sql)
    return int(out.strip()) if out.strip() else 0


M = {}

# ---- 1) 文档规模与状态 ----
M["doc_total"] = count("SELECT count(*) FROM documents;")
M["doc_parsed"] = count("SELECT count(*) FROM documents WHERE status='parsed';")
M["doc_awaiting"] = count("SELECT count(*) FROM documents WHERE status='awaiting_decision';")
M["doc_failed"] = count("SELECT count(*) FROM documents WHERE status IN ('failed','error');")
M["doc_status_rows"] = rows(
    "SELECT status, count(*) FROM documents GROUP BY status ORDER BY count DESC;"
)

# ---- 2) 上传即拦截率：任务闸门/异常拦截 ----
M["task_total"] = count("SELECT count(*) FROM document_tasks;")
M["task_gated"] = rows(
    "SELECT task_type, status, count(*) FROM document_tasks "
    "WHERE gate_reason IS NOT NULL OR status IN ('awaiting_decision','failed','error') "
    "GROUP BY task_type, status ORDER BY count DESC;"
)
M["task_gate_reasons"] = rows(
    "SELECT COALESCE(gate_reason,'(none)'), count(*) FROM document_tasks "
    "GROUP BY gate_reason ORDER BY count DESC;"
)
M["task_ocr"] = count(
    "SELECT count(*) FROM document_tasks WHERE task_type='parse' "
    "AND (gate_reason LIKE '%ocr%' OR gate_reason LIKE '%OCR%' OR gate_reason LIKE '%扫描%');"
)
M["task_warnings"] = count(
    "SELECT count(*) FROM document_tasks WHERE warnings IS NOT NULL AND warnings::text <> '[]';"
)

# ---- 3) 发现问题 ----
M["find_total"] = count("SELECT count(*) FROM check_findings;")
M["find_per_doc_avg"] = round(M["find_total"] / M["doc_parsed"], 2) if M["doc_parsed"] else 0
M["find_severity"] = rows(
    "SELECT severity, count(*) FROM check_findings GROUP BY severity ORDER BY count DESC;"
)
M["find_checker"] = rows(
    "SELECT checker, count(*) FROM check_findings GROUP BY checker ORDER BY count DESC;"
)
M["find_status"] = rows(
    "SELECT status, count(*) FROM check_findings GROUP BY status ORDER BY count DESC;"
)
M["find_per_doc_dist"] = rows(
    "SELECT bucket, count(*) FROM ("
    "  SELECT CASE WHEN n=0 THEN '0' WHEN n<=2 THEN '1-2' WHEN n<=5 THEN '3-5' "
    "  WHEN n<=10 THEN '6-10' ELSE '>10' END AS bucket FROM ("
    "    SELECT document_id, count(*) AS n FROM check_findings GROUP BY document_id"
    "  ) t"
    ") tt GROUP BY bucket ORDER BY min(CASE bucket WHEN '0' THEN 0 WHEN '1-2' THEN 1 "
    "WHEN '3-5' THEN 2 WHEN '6-10' THEN 3 ELSE 4 END);"
)
M["find_top_docs"] = rows(
    "SELECT d.filename, count(f.id) AS n FROM check_findings f "
    "JOIN documents d ON d.id=f.document_id "
    "GROUP BY d.filename ORDER BY n DESC LIMIT 10;"
)

# ---- 4) 用户分布 ----
M["doc_by_user"] = rows(
    "SELECT u.username, count(DISTINCT d.id) FROM documents d JOIN users u ON u.id=d.user_id "
    "GROUP BY u.username ORDER BY count DESC;"
)

with open(JSON_OUT, "w", encoding="utf-8") as f:
    json.dump(M, f, ensure_ascii=False, indent=2)

print(json.dumps(M, ensure_ascii=False, indent=2))
