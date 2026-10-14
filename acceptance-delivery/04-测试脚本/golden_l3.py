# -*- coding: utf-8 -*-
"""L3 业务价值代理指标：基于 L1 检查结果 + ground truth 计算。
指标：上传即拦截率 / 每份平均发现问题数 / 严重度分布 / 检出质量对照。
"""
import json
import os

GOLDEN_DIR = r"D:\projects\ai-doc-lint\corpus\acceptance_golden"


def main():
    l1 = json.load(open(os.path.join(GOLDEN_DIR, "l1_results.json"), encoding="utf-8"))
    gt = json.load(open(os.path.join(GOLDEN_DIR, "ground_truth.json"), encoding="utf-8"))
    gt_by_file = {g["file"]: g for g in gt}

    n = len(l1)
    docs_with_finding = [r for r in l1 if r.get("findings_total", 0) > 0]
    total_f = sum(r.get("findings_total", 0) for r in l1)
    sev = {}
    chk = {}
    for r in l1:
        for k, v in r.get("severity", {}).items():
            sev[k] = sev.get(k, 0) + v
        for k, v in r.get("checkers", {}).items():
            chk[k] = chk.get(k, 0) + v

    # 类型维度
    cat_stats = {}
    for r in l1:
        c = r["category"]
        s = cat_stats.setdefault(c, {"docs": 0, "findings": 0})
        s["docs"] += 1
        s["findings"] += r.get("findings_total", 0)

    # ground truth 模板缺失对照：缺失标注 vs 系统检出
    gt_missing_docs = [g for g in gt if g["fields"]["模板缺失"]]
    gt_missing_files = {g["file"]: g["fields"]["模板缺失"] for g in gt_missing_docs}

    # 系统发现的全部 message
    all_msgs = []
    for r in l1:
        for s in r.get("sample", []):
            all_msgs.append((r["file"], s.get("message", "")))
    real_hits = [m for m in all_msgs if "签定" in m[1]]
    ctx_fp = [m for m in all_msgs if any(k in m[1] for k in ["由其", "因该", "审报"])]

    out = {
        "total_docs": n,
        "parsed_docs": sum(1 for r in l1 if r["status"] == "parsed"),
        "failed_docs": sum(1 for r in l1 if r["status"] == "failed"),
        "docs_with_findings": len(docs_with_finding),
        "upload_block_rate": round(len(docs_with_finding) / n * 100, 1),
        "total_findings": total_f,
        "avg_findings_per_doc": round(total_f / n, 2),
        "severity": sev,
        "checkers": chk,
        "by_category": {k: v for k, v in cat_stats.items()},
        "gt_template_missing_docs": len(gt_missing_docs),
        "real_typo_hits": len(real_hits),
        "contextual_fp": len(ctx_fp),
        "contextual_fp_detail": ctx_fp[:8],
    }
    with open(os.path.join(GOLDEN_DIR, "l3_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    for k in ["total_docs", "parsed_docs", "failed_docs", "docs_with_findings",
              "upload_block_rate", "total_findings", "avg_findings_per_doc",
              "severity", "checkers", "by_category", "gt_template_missing_docs",
              "real_typo_hits", "contextual_fp"]:
        print(k, "=", out[k])


if __name__ == "__main__":
    main()
