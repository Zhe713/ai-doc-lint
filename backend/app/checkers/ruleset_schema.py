"""规则包 JSON Schema（P2-3 规则包 JSON 数据化）。

- 每类规则包给出结构化字段定义（中文标签/类型/是否必填/人话说明/示例），
  供前端"规则管理界面"（P3）按 schema 渲染表单，替代手写 YAML；
- schema 与 validate.py 的校验口径一致，保证"表单产出的 JSON 必然可加载"。
"""

from __future__ import annotations

PACK_TYPES = ("format", "clause", "field", "cross")

# 四类规则包的表单化字段定义（P3 规则管理界面渲染用）
RULESET_SCHEMAS: dict[str, dict] = {
    "format": {
        "label": "格式规则包",
        "plain_intro": "管文档长什么样：纸张大小、页边距、字体字号、缩进和标题层级。这些是客观测量，系统直接判定，不调用大模型。",
        "fields": [
            {"key": "page.size.expected_mm", "label": "纸张尺寸(mm×mm)", "type": "number[]", "required": True,
             "default": [210, 297],
             "help": "希望文档用多大的纸，按毫米填写宽和高。",
             "example": "A4 纸填 [210, 297]；A3 纸填 [297, 420]"},
            {"key": "page.size.tolerance_mm", "label": "纸张容差(mm)", "type": "number", "required": True,
             "default": 3,
             "help": "实际纸张和标准尺寸允许相差多少毫米，差得比这个小就不算问题。",
             "example": "填 3 表示差 3 毫米以内不报错，适合扫描件轻微偏差"},
            {"key": "page.size.severity", "label": "纸张不合格的严重度", "type": "select", "required": True,
             "default": "warning", "options": ["error", "warning", "info"],
             "help": "纸张尺寸不符时，这条在报告里算错误、警告还是提示。"},
            {"key": "page.margin_cm.top", "label": "上边距区间(cm)", "type": "number[]", "required": True,
             "default": [2.0, 4.0],
             "help": "正文距离页面上边的合理范围，按厘米填最小值和最大值。",
             "example": "[2.0, 4.0] 表示上页边距在 2 到 4 厘米之间都合格"},
            {"key": "page.margin_cm.bottom", "label": "下边距区间(cm)", "type": "number[]", "required": True,
             "default": [2.0, 4.0], "help": "正文距离页面下边的合理范围，按厘米填。"},
            {"key": "page.margin_cm.left", "label": "左边距区间(cm)", "type": "number[]", "required": True,
             "default": [2.0, 3.5], "help": "正文距离页面左边的合理范围，按厘米填。"},
            {"key": "page.margin_cm.right", "label": "右边距区间(cm)", "type": "number[]", "required": True,
             "default": [2.0, 3.5], "help": "正文距离页面右边的合理范围，按厘米填。"},
            {"key": "page.margin_cm.severity", "label": "页边距不合格的严重度", "type": "select", "required": True,
             "default": "warning", "options": ["error", "warning", "info"],
             "help": "页边距超出范围时，这条在报告里算错误、警告还是提示。"},
            {"key": "font.body_allow", "label": "正文允许字体", "type": "string[]", "required": True,
             "default": ["宋体", "仿宋", "仿宋_GB2312", "黑体", "楷体", "Times New Roman"],
             "help": "正文允许使用哪些字体，用了列表之外的字体会提示。",
             "example": "正式合同常用宋体、仿宋；可按需增删"},
            {"key": "font.body_size_pt", "label": "正文字号区间(pt)", "type": "number[]", "required": True,
             "default": [10.5, 16],
             "help": "正文字号的合理范围，按磅（pt）填最小值和最大值。",
             "example": "小四是 12pt，四号是 14pt；[10.5, 16] 覆盖常见正文"},
            {"key": "font.severity", "label": "字体字号不合格的严重度", "type": "select", "required": True,
             "default": "warning", "options": ["error", "warning", "info"],
             "help": "字体或字号不符时，这条在报告里算错误、警告还是提示。"},
            {"key": "paragraph.first_line_indent_chars", "label": "首行缩进字符数", "type": "number",
             "required": True, "default": 2,
             "help": "中文正文每段开头应空几个字，常规是 2 个字符。",
             "example": "填 2 即要求每段开头空两格"},
            {"key": "paragraph.unindented_ratio", "label": "未缩进段落容忍比例", "type": "number",
             "required": True, "default": 0.3,
             "help": "允许有多大比例的段落不缩进，超过这个比例才提示，避免个别短段落触发误报。",
             "example": "填 0.3 表示 30% 以内的段落没缩进可以接受"},
            {"key": "paragraph.min_chars", "label": "缩进判定最小字数", "type": "number", "required": True,
             "default": 15,
             "help": "短于这个字数的段落不检查缩进，标题、短句不受影响。",
             "example": "填 15 表示不足 15 个字的段落不要求缩进"},
            {"key": "paragraph.severity", "label": "段落排版不合格的严重度", "type": "select", "required": True,
             "default": "info", "options": ["error", "warning", "info"],
             "help": "缩进不符时，这条在报告里算错误、警告还是提示。"},
            {"key": "heading.enabled", "label": "标题层级检查", "type": "boolean", "required": False,
             "default": True,
             "help": "是否检查标题编号是否跳级（如直接从“一、”跳到“1.”）。",
             "example": "开启后，中间缺层级会提示补全"},
            {"key": "heading.severity", "label": "标题层级不合格的严重度", "type": "select", "required": True,
             "default": "info", "options": ["error", "warning", "info"],
             "help": "标题编号跳级时，这条在报告里算错误、警告还是提示。"},
        ],
        "severity": "每个检查项可单独设置严重程度：error（错误）、warning（警告）、info（提示）",
    },
    "clause": {
        "label": "条款完整性规则包",
        "item_label": "条款",
        "plain_intro": "管一份合同必须包含哪些内容，比如当事人信息、违约责任。系统先找关键词，拿不准的再交给大模型结合上下文确认。",
        "fields": [
            {"key": "id", "label": "规则 ID", "type": "string", "required": True,
             "help": "这条规则的唯一编号，建议用英文，方便系统识别。",
             "example": "clause.breach 表示违约责任条款"},
            {"key": "name", "label": "条款名称", "type": "string", "required": True,
             "help": "给人看的中文名称，会显示在报告里。",
             "example": "违约责任"},
            {"key": "required", "label": "是否必含", "type": "boolean", "required": True, "default": True,
             "help": "打开表示合同里必须有这条，缺失会提示；关闭表示可选，不检查。",
             "example": "违约责任通常必含；一些特殊约定可设为可选"},
            {"key": "severity", "label": "缺失严重度", "type": "select", "required": True,
             "options": ["error", "warning", "info"],
             "help": "缺这条时问题的严重程度：error 最严重，warning 一般，info 仅提示。"},
            {"key": "strong", "label": "强关键词(命中即存在)", "type": "string[]", "required": True,
             "help": "文档里只要出现这些词，就直接认定条款存在，不调用大模型。",
             "example": "违约责任的强关键词：违约责任、违约金、违约条款"},
            {"key": "weak", "label": "弱关键词(命中进入复核)", "type": "string[]", "required": False,
             "default": [],
             "help": "出现这些词还不能确定，系统会把上下文交给大模型复核，减少误判。",
             "example": "违约责任的弱关键词：赔偿损失、逾期"},
        ],
        "structure": {"version": 1, "doc_types": ["contract"], "clauses": []},
    },
    "field": {
        "label": "字段抽取规则包",
        "item_label": "字段",
        "plain_intro": "管从合同里自动提取哪些信息，比如合同金额、签订日期、甲方名称，提取后可在报告和比对中使用。",
        "fields": [
            {"key": "key", "label": "字段键", "type": "string", "required": True,
             "help": "字段的英文标识，系统内部使用。",
             "example": "contract_amount 表示合同金额"},
            {"key": "label", "label": "字段中文名", "type": "string", "required": True,
             "help": "给人看的字段名称。",
             "example": "合同金额"},
            {"key": "type", "label": "值类型", "type": "select", "required": True,
             "options": ["text", "number", "date", "money", "party"],
             "help": "这个字段装的是什么类型的数据：文字、数字、日期、金额还是当事人。",
             "example": "金额选 money，签订日期选 date，甲方名称选 party"},
            {"key": "required", "label": "必填字段", "type": "boolean", "required": True, "default": True,
             "help": "打开表示该字段应被提取到，缺失时可在报告中体现。"},
            {"key": "patterns", "label": "抽取模式", "type": "string[]", "required": True,
             "help": "系统按这些写法去原文里定位字段，可填多个常见表达。",
             "example": "合同金额的模式：合同总价、合同金额、总价款"},
        ],
        "structure": {"version": 1, "doc_types": ["contract"], "fields": []},
    },
    "cross": {
        "label": "交叉勾稽规则包",
        "item_label": "勾稽规则",
        "plain_intro": "管不同字段之间是否对得上，比如大写金额和小写金额是否一致，属于确定性核对，不调用大模型。",
        "fields": [
            {"key": "id", "label": "规则 ID", "type": "string", "required": True,
             "help": "这条勾稽规则的唯一英文编号。",
             "example": "cross.amount"},
            {"key": "name", "label": "规则名称", "type": "string", "required": True,
             "help": "给人看的中文名称。",
             "example": "金额大小写一致性"},
            {"key": "fields", "label": "关联字段", "type": "string[]", "required": True,
             "help": "要互相核对的字段键名，填两个或以上。",
             "example": "['amount_words', 'amount_digits'] 表示大写金额与小写金额"},
            {"key": "severity", "label": "不一致严重度", "type": "select", "required": True,
             "options": ["error", "warning", "info"],
             "help": "核对不一致时的严重程度，金额对不上通常设为 error。"},
            {"key": "description", "label": "规则说明", "type": "string", "required": False,
             "help": "用一句话说明这条规则核对什么，方便日后维护。",
             "example": "核对大写金额与小写金额是否相等"},
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
