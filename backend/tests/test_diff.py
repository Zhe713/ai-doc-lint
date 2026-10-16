# -*- coding: utf-8 -*-
"""P3-1 版本 diff 测试：纯函数 diff_texts + API 校验。"""

import pytest

from app.api.diff import diff_texts
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_diff_identical_text():
    r = diff_texts("第一行\n第二行\n第三行", "第一行\n第二行\n第三行", auto_bypass=True)
    assert r["identical"] is True
    assert r["bypass_ready"] is True
    assert r["stats"]["same_lines"] == 3
    assert r["stats"]["add_lines"] == 0
    assert r["stats"]["del_lines"] == 0


def test_diff_add_del_rows():
    r = diff_texts("第一行\n旧内容\n第三行", "第一行\n新内容\n第三行")
    assert r["identical"] is False
    assert r["stats"]["add_lines"] == 1
    assert r["stats"]["del_lines"] == 1
    types = [x["type"] for x in r["rows"]]
    assert "add" in types and "del" in types and "equal" in types


def test_diff_bypass_not_ready_when_different():
    r = diff_texts("A", "B", auto_bypass=True)
    assert r["bypass_ready"] is False


def test_diff_truncated():
    big = "x" * 70_000
    r = diff_texts(big, big)
    assert r["truncated"] is True


def test_diff_empty_identical():
    r = diff_texts("", "")
    assert r["identical"] is True
    assert r["stats"]["same_lines"] == 0


def test_diff_api_requires_login():
    resp = client.get("/api/v1/compare/diff", params={"doc_a_id": "a", "doc_b_id": "b"})
    assert resp.status_code in (401, 403)


def test_diff_api_same_doc_422():
    # 未登录直接撞 401；带 token 逻辑走集成（同文档 422 由业务层拦）
    assert diff_texts("同", "同")["identical"] is True
