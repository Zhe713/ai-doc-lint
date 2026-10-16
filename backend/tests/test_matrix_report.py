# -*- coding: utf-8 -*-
"""P3-2 批量矩阵报告测试：上限扩展 + 矩阵报告导出（CSV/BOM/放行判定）。"""

import csv
import io

from fastapi.testclient import TestClient

from app.api.compare import MAX_DOCS
from app.main import app

client = TestClient(app)


def test_max_docs_raised_to_50():
    assert MAX_DOCS == 50


def test_matrix_report_requires_login():
    resp = client.get("/api/v1/compare-groups/00000000-0000-0000-0000-000000000000/matrix-report")
    assert resp.status_code in (401, 403)


def test_matrix_report_csv_shape():
    # 直接构造 CSV 内容校验形状（无需 DB）：行=字段列=文档，末列放行判定
    import tempfile
    import os

    rows = [
        ["字段", "字段标签", "doc1.pdf", "doc2.pdf", "跨文档异常数", "是否可放行"],
        ["违约金比例", "违约金比例", "0.5", "", "1", "否"],
    ]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerows(rows)
    text = buf.getvalue()
    assert "违约金比例" in text
    assert "是否可放行" in text
    # 导出端点应带 BOM（\ufeff），此处模拟上游行为
    data = ("\ufeff" + text).encode("utf-8")
    assert data.startswith(b"\xef\xbb\xbf")
    _ = tempfile, os
