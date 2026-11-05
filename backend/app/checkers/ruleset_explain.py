"""把规则包翻译成「人话」。

规则包本质是参数集合（`210, 297`、`0.3`、`10.5, 16`），非技术用户看不懂，
技术人员也只能猜。本模块把任意一份规则包内容渲染成一组可读条目：

    检查什么 → 具体要求 → 不合格会怎样 → 这一条是纯规则判定还是大模型参与

前端规则页 / 报告页都用它，保证「规则的唯一解释来源」在后端，不在前端硬编码。
"""

from __future__ import annotations

from typing import Any

# 判定依据：决定这条规则要不要花 token，也是「AI 体现在哪里」的答案之一
BASIS_RULE = "rule"
BASIS_HYBRID = "hybrid"
BASIS_LLM = "llm"

BASIS_LABELS = {
    BASIS_RULE: "规则判定（不调用大模型）",
    BASIS_HYBRID: "规则初筛 + 大模型复核",
    BASIS_LLM: "大模型语义判定",
}

SEVERITY_LABELS = {"error": "错误", "warning": "警告", "info": "提示"}

# 常见纸张尺寸（毫米），用于把 [210, 297] 说成「A4」
_PAPER_SIZES: dict[tuple[int, int], str] = {
    (210, 297): "A4",
    (297, 420): "A3",
    (148, 210): "A5",
    (105, 148): "A6",
    (182, 257): "B5",
    (176, 250): "B5（ISO）",
    (216, 279): "Letter",
    (184, 260): "16 开",
}


def _get(content: Any, path: str, default=None):
    cur = content
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _paper_name(mm) -> str:
    if not isinstance(mm, (list, tuple)) or len(mm) < 2:
        return "未设置"
    try:
        w, h = int(round(float(mm[0]))), int(round(float(mm[1])))
    except (TypeError, ValueError):
        return f"{mm[0]}×{mm[1]} 毫米"
    name = _PAPER_SIZES.get((w, h)) or _PAPER_SIZES.get((h, w))
    return f"{name}（{w}×{h} 毫米）" if name else f"{w}×{h} 毫米"


def _range_text(value, unit: str) -> str:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return f"{value[0]}–{value[1]} {unit}"
    if value is None:
        return "未设置"
    return f"{value} {unit}"


def _item(title: str, detail: str, *, severity=None, basis=BASIS_RULE, rule_id: str | None = None) -> dict:
    return {
        "title": title,
        "detail": detail,
        "severity": severity,
        "severity_label": SEVERITY_LABELS.get(severity or "", "提示"),
        "basis": basis,
        "basis_label": BASIS_LABELS.get(basis, basis),
        "rule_id": rule_id,
    }


# ---------------- 格式规则 ----------------

def _explain_format(content: dict) -> list[dict]:
    items: list[dict] = []
    size = _get(content, "page.size", {}) or {}
    if size.get("expected_mm"):
        sev = size.get("severity")
        tol = size.get("tolerance_mm")
        detail = f"文档应为 {_paper_name(size['expected_mm'])}"
        if tol:
            detail += f"，实际尺寸相差 {tol} 毫米以内都算合格（扫描件常见轻微偏差）"
        items.append(_item("纸张尺寸", detail + "。", severity=sev, rule_id="format.page.size"))

    margin = _get(content, "page.margin_cm", {}) or {}
    sides = [(k, margin.get(k)) for k in ("top", "bottom", "left", "right")]
    if any(v for _, v in sides):
        label = {"top": "上", "bottom": "下", "left": "左", "right": "右"}
        parts = [f"{label[k]} {_range_text(v, '厘米')}" for k, v in sides if v]
        items.append(_item(
            "页边距", "正文与纸张边缘的距离应在：" + "、".join(parts) + "。",
            severity=margin.get("severity"), rule_id="format.page.margin",
        ))

    font = _get(content, "font", {}) or {}
    if font.get("body_allow"):
        items.append(_item(
            "正文字体", "只允许使用：" + "、".join(font["body_allow"]) + "。用了清单外的字体会提示。",
            severity=font.get("severity"), rule_id="format.font.body",
        ))
    if font.get("body_size_pt"):
        items.append(_item(
            "正文字号",
            f"正文字号应在 {_range_text(font['body_size_pt'], '磅(pt)')} 之间"
            "（小四 12pt、四号 14pt、三号 16pt）。",
            severity=font.get("severity"), rule_id="format.font.size",
        ))

    para = _get(content, "paragraph", {}) or {}
    if para.get("first_line_indent_chars") is not None:
        indent = para["first_line_indent_chars"]
        extra = ""
        if para.get("unindented_ratio") is not None:
            extra = f"允许最多 {round(float(para['unindented_ratio']) * 100)}% 的段落不缩进，"
        if para.get("min_chars") is not None:
            extra += f"不足 {para['min_chars']} 字的短段落（标题、一句话）不检查。"
        items.append(_item(
            "首行缩进", f"每个自然段开头空 {indent} 个字符。{extra}",
            severity=para.get("severity"), rule_id="format.paragraph.indent",
        ))

    heading = _get(content, "heading", {}) or {}
    if heading.get("enabled"):
        items.append(_item(
            "标题层级", "检查标题编号有没有跳级（例如从「一、」直接跳到「1.」），跳级会提示。",
            severity=heading.get("severity"), rule_id="format.heading.sequence",
        ))
    return items


# ---------------- 条款完整性 ----------------

def _explain_clause(content: dict) -> list[dict]:
    items: list[dict] = []
    for clause in content.get("clauses") or []:
        name = clause.get("name") or clause.get("id") or "未命名条款"
        rule_id = clause.get("id")
        strong = clause.get("strong") or []
        weak = clause.get("weak") or []
        required = clause.get("required", True)
        if not required:
            items.append(_item(
                name, "可选条款：缺失不会提示，只在原文出现时做一致性参考。",
                severity=clause.get("severity"), basis=BASIS_RULE, rule_id=rule_id,
            ))
            continue
        parts = [f"合同必须包含「{name}」条款。"]
        if strong:
            parts.append("原文出现 " + "、".join(f"「{w}」" for w in strong[:5])
                         + " 中任一个，即判定条款存在（不调用大模型）。")
        if weak:
            parts.append("只出现 " + "、".join(f"「{w}」" for w in weak[:5])
                         + " 这类弱信号时，交给大模型结合上下文确认是否真的约定了本条。")
        else:
            parts.append("若一个关键词都没命中，交给大模型按章节结构做语义确认，"
                         "确认整份文档确实没有才报缺失，避免换个说法就误报。")
        items.append(_item(
            name, "".join(parts),
            severity=clause.get("severity"),
            basis=BASIS_HYBRID if weak else BASIS_LLM,
            rule_id=rule_id,
        ))
    return items


# ---------------- 字段抽取 ----------------

def _explain_field(content: dict) -> list[dict]:
    items: list[dict] = []
    type_labels = {
        "text": "文字", "number": "数字", "date": "日期",
        "money": "金额", "party": "当事人",
    }
    for field in content.get("fields") or []:
        label = field.get("label") or field.get("key") or "未命名字段"
        rule_id = field.get("key")
        ftype = type_labels.get(field.get("type") or "", field.get("type") or "文字")
        patterns = field.get("patterns") or []
        detail = f"从原文中自动提取「{label}」（{ftype}型）。"
        if patterns:
            detail += "识别的写法包括：" + "、".join(f"「{p}」" for p in patterns[:6]) + "。"
        detail += ("先用规则正则直接抓取，零 token；抓不到时（如开启交叉比对）"
                   "由大模型补抽，并把来源原文回填以便核对。")
        items.append(_item(label, detail, basis=BASIS_RULE, rule_id=rule_id))
    return items


# ---------------- 交叉勾稽 ----------------

def _explain_cross(content: dict) -> list[dict]:
    items: list[dict] = []
    for check in content.get("checks") or []:
        name = check.get("name") or check.get("id") or "未命名勾稽"
        rule_id = check.get("id")
        fields = check.get("fields") or []
        detail = "核对 " + " 与 ".join(f"「{f}」" for f in fields) if fields else "核对关联字段"
        detail += " 是否一致。"
        desc = (check.get("description") or "").strip()
        if desc:
            detail += desc.rstrip("。") + "。"
        detail += "属于确定性计算，不调用大模型。"
        items.append(_item(name, detail, severity=check.get("severity"), basis=BASIS_RULE, rule_id=rule_id))
    return items


_EXPLAINERS = {
    "format": _explain_format,
    "clause": _explain_clause,
    "field": _explain_field,
    "cross": _explain_cross,
}

_PACK_TITLES = {
    "format": "格式规则",
    "clause": "条款完整性规则",
    "field": "字段抽取规则",
    "cross": "交叉勾稽规则",
}


def explain_pack(pack_type: str, content: dict) -> dict:
    """返回 {pack_type, title, items, counts}；未知类型抛 ValueError。"""
    if pack_type not in _EXPLAINERS:
        raise ValueError(f"未知规则包类型: {pack_type}")
    if not isinstance(content, dict):
        content = {}
    items = _EXPLAINERS[pack_type](content)
    counts = {"rule": 0, "hybrid": 0, "llm": 0}
    for it in items:
        counts[it["basis"]] = counts.get(it["basis"], 0) + 1
    return {
        "pack_type": pack_type,
        "title": _PACK_TITLES[pack_type],
        "total": len(items),
        "items": items,
        "counts": counts,
    }
