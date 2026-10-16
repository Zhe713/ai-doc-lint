"""规则包 JSON Schema（P2-3 规则包 JSON 数据化）。

- 每类规则包给出结构化字段定义（中文标签/类型/是否必填/说明），
  供前端"规则管理界面"（P3）按 schema 渲染表单，替代手写 YAML；
- schema 与 validate.py 的校验口径一致，保证"表单产出的 JSON 必然可加载"。
"""

from __future__ import annotations

PACK_TYPES = ("format", "clause", "field", "cross")

# 四类规则包的表单化字段定义（P3 规则管理界面渲染用）
RULESET_SCHEMAS: dict[str, dict] = {
    "format": {
        "label": "格式规则包",
        "fields": [
            {"key": "page.size.expected_mm", "label": "纸张尺寸(mm×mm)", "type": "number[]", "required": True,
             "default": [210, 297], "help": "期望纸张尺寸，如 A4 为 210×297"},
            {"key": "page.size.tolerance_mm", "label": "纸张容差(mm)", "type": "number", "required": True,
             "default": 3, "help": "与期望尺寸的允许偏差"},
            {"key": "page.margin_cm.top", "label": "上边距区间(cm)", "type": "number[]", "required": True,
             "default": [2.0, 4.0]},
            {"key": "page.margin_cm.bottom", "label": "下边距区间(cm)", "type": "number[]", "required": True,
             "default": [2.0, 4.0]},
            {"key": "page.margin_cm.left", "label": "左边距区间(cm)", "type": "number[]", "required": True,
             "default": [2.0, 3.5]},
            {"key": "page.margin_cm.right", "label": "右边距区间(cm)", "type": "number[]", "required": True,
             "default": [2.0, 3.5]},
            {"key": "font.body_allow", "label": "正文允许字体", "type": "string[]", "required": True,
             "default": ["宋体", "仿宋", "仿宋_GB2312", "黑体", "楷体", "Times New Roman"]},
            {"key": "font.body_size_pt", "label": "正文字号区间(pt)", "type": "number[]", "required": True,
             "default": [10.5, 16]},
            {"key": "paragraph.first_line_indent_chars", "label": "首行缩进字符数", "type": "number", "required": True,
             "default": 2},
            {"key": "paragraph.unindented_ratio", "label": "未缩进段落容忍比例", "type": "number", "required": True,
             "default": 0.3},
            {"key": "paragraph.min_chars", "label": "缩进判定最小字数", "type": "number", "required": True,
             "default": 15},
            {"key": "heading.enabled", "label": "标题层级检查", "type": "boolean", "required": False, "default": True},
        ],
        "severity": "page/font/paragraph/heading 各级均可带 severity（warning/info/error）",
    },
    "clause": {
        "label": "条款完整性规则包",
        "item_label": "条款",
        "fields": [
            {"key": "id", "label": "规则 ID", "type": "string", "required": True,
             "help": "唯一标识，如 clause.parties"},
            {"key": "name", "label": "条款名称", "type": "string", "required": True},
            {"key": "required", "label": "是否必含", "type": "boolean", "required": True, "default": True},
            {"key": "severity", "label": "缺失严重度", "type": "select", "required": True,
             "options": ["error", "warning", "info"]},
            {"key": "strong", "label": "强关键词(命中即存在)", "type": "string[]", "required": True},
            {"key": "weak", "label": "弱关键词(命中进入复核)", "type": "string[]", "required": False, "default": []},
        ],
        "structure": {"version": 1, "doc_types": ["contract"], "clauses": []},
    },
    "field": {
        "label": "字段抽取规则包",
        "item_label": "字段",
        "fields": [
            {"key": "key", "label": "字段键", "type": "string", "required": True},
            {"key": "label", "label": "字段中文名", "type": "string", "required": True},
            {"key": "type", "label": "值类型", "type": "select", "required": True,
             "options": ["text", "number", "date", "money", "party"]},
            {"key": "required", "label": "必填字段", "type": "boolean", "required": True, "default": True},
            {"key": "patterns", "label": "抽取模式", "type": "string[]", "required": True},
        ],
        "structure": {"version": 1, "doc_types": ["contract"], "fields": []},
    },
    "cross": {
        "label": "交叉勾稽规则包",
        "item_label": "勾稽规则",
        "fields": [
            {"key": "id", "label": "规则 ID", "type": "string", "required": True},
            {"key": "name", "label": "规则名称", "type": "string", "required": True},
            {"key": "fields", "label": "关联字段", "type": "string[]", "required": True,
             "help": "如 ['amount_words', 'amount_digits']"},
            {"key": "severity", "label": "不一致严重度", "type": "select", "required": True,
             "options": ["error", "warning", "info"]},
            {"key": "description", "label": "规则说明", "type": "string", "required": False},
        ],
        "structure": {"version": 1, "doc_types": ["contract"], "checks": []},
    },
}


def ruleset_schema(pack_type: str) -> dict:
    """返回指定类型的表单化 schema；未知类型抛 ValueError。"""
    if pack_type not in RULESET_SCHEMAS:
        raise ValueError(f"未知规则包类型: {pack_type}")
    return RULESET_SCHEMAS[pack_type]


def all_ruleset_schemas() -> dict:
    """返回四类 schema（P3 规则管理界面一次性拉取）。"""
    return RULESET_SCHEMAS
