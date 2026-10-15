# -*- coding: utf-8 -*-
"""生成 golden 集版本清单 golden_manifest.json（W7-5 golden 集版本化）。"""
import json
from datetime import date
from pathlib import Path

GOLDEN_DIR = Path(r"D:\projects\ai-doc-lint\corpus\acceptance_golden")
RESULTS = GOLDEN_DIR / "l1_results.json"
OUT = GOLDEN_DIR / "golden_manifest.json"

rows = json.loads(RESULTS.read_text(encoding="utf-8"))
doc_ids = [r["doc_id"] for r in rows if r.get("doc_id")]

manifest = {
    "version": "v1.0.0",
    "updated_at": date.today().isoformat(),
    "description": "验收 golden 集：40 份真实合同（政采/示范文本/已有真实语料），用于自学习闭环回归评估",
    "doc_count": len(doc_ids),
    "source": "l1_results.json",
    "doc_ids": doc_ids,
    "changelog": [
        {
            "version": "v1.0.0",
            "date": "2026-10-14",
            "change": "初版：40 份真实合同入库（含 build/trade/agri 等类别）",
        }
    ],
    "usage": "调优候选词先对 golden 集做回归验证：会掩盖 golden 真实问题则不自动生效；新增/调整 golden 需升版本号并追加 changelog",
}
OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("written", OUT, "docs=", len(doc_ids))
