"""格式检查器（W3 Day12）。

- docx：python-docx 精确读取节（纸张/页边距）、run（字体/字号）、段落缩进、标题层级；
- pdf：pdfium 启发式检查纸张与标题层级；页边距/字体/缩进无法可靠获取 → 显式 skip；
- txt/md：无版式概念，全部 skip。

能力边界原则：不能可靠检查的规则记 skipped，绝不产生"看起来对"的误报。
"""

import io
import logging
import re

from app.checkers.loader import load_format_rules
from app.db import storage
from app.models.document import CHECKER_FORMAT, Document

log = logging.getLogger("checker.format")

CN_NUM = r"[一二三四五六七八九十百]+"
HEADING_PATTERNS = [
    (1, re.compile(rf"^{CN_NUM}、")),
    (2, re.compile(rf"^（{CN_NUM}）")),
    (3, re.compile(r"^\d+[.、]")),
    (4, re.compile(r"^（\d+）")),
]

# txt/md 下全部跳过的规则
ALL_RULE_IDS = [
    "format.page.size",
    "format.page.margin",
    "format.font.body",
    "format.font.size",
    "format.paragraph.indent",
    "format.heading.sequence",
]


class FormatChecker:
    checker = CHECKER_FORMAT

    def __init__(self, db, document: Document, collector, review_options=None):
        self.db = db
        self.document = document
        self.collector = collector
        self.rules = load_format_rules()
        self.ext = (document.ext or "").lower()

    def run(self) -> None:
        data = storage.get_object_bytes(self.document.storage_key)
        if self.ext == "docx":
            self._check_docx(data)
        elif self.ext == "pdf":
            self._check_pdf(data)
        else:
            for rule in ALL_RULE_IDS:
                self.collector.note_skipped(rule)

    # ---------------- docx ----------------

    def _check_docx(self, data: bytes) -> None:
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(data))
        self._check_sections_docx(doc)
        self._check_fonts_docx(doc)
        self._check_indent_docx(doc)
        if self.rules["heading"].get("enabled", True):
            self._check_heading_sequence(
                [p.text for p in doc.paragraphs], location_kind="paragraph"
            )

    def _check_sections_docx(self, doc) -> None:
        page = self.rules["page"]
        ew, eh = page["size"]["expected_mm"]
        tol = page["size"]["tolerance_mm"]
        for idx, sec in enumerate(doc.sections):
            w_mm, h_mm = sec.page_width.mm, sec.page_height.mm
            if abs(w_mm - ew) > tol or abs(h_mm - eh) > tol:
                self.collector.add(
                    checker=self.checker, rule_id="format.page.size",
                    severity=page["size"]["severity"],
                    message=f"第{idx + 1}节纸张为 {w_mm:.0f}×{h_mm:.0f}mm，非标准 A4（{ew}×{eh}mm）",
                    suggestion="在「布局-纸张大小」中选择 A4",
                    location={"section": idx},
                )

            margins = {
                "top": (sec.top_margin, 2.54),
                "bottom": (sec.bottom_margin, 2.54),
                "left": (sec.left_margin, 3.17),
                "right": (sec.right_margin, 3.17),
            }
            side_label = {"top": "上", "bottom": "下", "left": "左", "right": "右"}
            for side, (length, default_cm) in margins.items():
                lo, hi = page["margin_cm"][side]
                cm = default_cm if length is None else length.cm
                if cm < lo or cm > hi:
                    self.collector.add(
                        checker=self.checker, rule_id="format.page.margin",
                        severity=page["margin_cm"]["severity"],
                        message=(
                            f"第{idx + 1}节{side_label[side]}页边距 {cm:.2f}cm，"
                            f"超出建议区间 {lo}-{hi}cm"
                        ),
                        suggestion="在「布局-页边距」中调整页边距",
                        location={"section": idx, "side": side},
                    )

    def _iter_body_paragraphs(self, doc):
        for idx, p in enumerate(doc.paragraphs):
            style_name = (p.style.name if p.style else "") or ""
            if style_name.startswith("Heading") or style_name.startswith("标题"):
                continue
            text = p.text.strip()
            if text:
                yield idx, p, text

    @staticmethod
    def _east_asia_font(run) -> str | None:
        from docx.oxml.ns import qn

        rPr = run._element.rPr
        if rPr is not None:
            rFonts = rPr.find(qn("w:rFonts"))
            if rFonts is not None:
                return rFonts.get(qn("w:eastAsia")) or run.font.name
        return run.font.name

    def _check_fonts_docx(self, doc) -> None:
        font_rules = self.rules["font"]
        allow = font_rules["body_allow"]
        size_lo, size_hi = font_rules["body_size_pt"]
        severity = font_rules["severity"]
        font_hits: list[tuple[int, str, str]] = []
        size_hits: list[tuple[int, str, float]] = []

        for idx, p, text in self._iter_body_paragraphs(doc):
            for run in p.runs:
                if not run.text.strip():
                    continue
                ea = self._east_asia_font(run)
                # 仅检查含中文的 run，西文 run 交给白名单中的西文字体
                has_cjk = bool(re.search(r"[\u4e00-\u9fff]", run.text))
                if has_cjk and ea and ea not in allow and len(font_hits) < 5:
                    font_hits.append((idx, text[:30], ea))
                if run.font.size is not None:
                    pt = run.font.size.pt
                    if (pt < size_lo or pt > size_hi) and len(size_hits) < 5:
                        size_hits.append((idx, text[:30], pt))

        for idx, snippet, ea in font_hits:
            self.collector.add(
                checker=self.checker, rule_id="format.font.body",
                severity=severity,
                message=f"段落使用字体「{ea}」，不在建议字体范围（{ '、'.join(allow[:5]) }等）",
                suggestion="选中正文，在「开始-字体」中统一为宋体或仿宋",
                location={"paragraph_index": idx, "snippet": snippet},
            )
        for idx, snippet, pt in size_hits:
            self.collector.add(
                checker=self.checker, rule_id="format.font.size",
                severity=severity,
                message=f"段落字号 {pt:g}pt，超出建议区间 {size_lo:g}-{size_hi:g}pt",
                suggestion="选中正文，在「开始-字号」中统一为小四或四号",
                location={"paragraph_index": idx, "snippet": snippet},
            )

    def _check_indent_docx(self, doc) -> None:
        pr = self.rules["paragraph"]
        min_chars = pr["min_chars"]
        total = 0
        unindented: list[tuple[int, str]] = []
        for idx, p, text in self._iter_body_paragraphs(doc):
            if len(text) < min_chars:
                continue
            total += 1
            indent = p.paragraph_format.first_line_indent
            # 2 字符 ≈ 19-26pt（小四到三号）；None/0 视为未缩进
            ok = indent is not None and 19 <= indent.pt <= 26
            if not ok and len(unindented) < 5:
                unindented.append((idx, text[:30]))

        if total and len(unindented) / total > pr["unindented_ratio"]:
            self.collector.add(
                checker=self.checker, rule_id="format.paragraph.indent",
                severity=pr["severity"],
                message=f"约 {len(unindented)}/{total} 个正文长段落未首行缩进 2 字符",
                suggestion="选中正文，设置首行缩进 2 字符",
                location={"paragraphs": [i for i, _ in unindented]},
            )

    # ---------------- pdf ----------------

    def _check_pdf(self, data: bytes) -> None:
        import pypdfium2 as pdfium

        page = self.rules["page"]
        ew, eh = page["size"]["expected_mm"]
        tol = page["size"]["tolerance_mm"]

        pdf = pdfium.PdfDocument(io.BytesIO(data))
        bad_pages: list[int] = []
        page_texts: list[str] = []
        for i, pdf_page in enumerate(pdf):
            w_pt, h_pt = pdf_page.get_size()
            w_mm, h_mm = w_pt / 72 * 25.4, h_pt / 72 * 25.4
            if abs(w_mm - ew) > tol or abs(h_mm - eh) > tol:
                bad_pages.append(i + 1)
            tp = pdf_page.get_textpage()
            try:
                page_texts.append(tp.get_text_range() or "")
            finally:
                tp.close()

        if bad_pages:
            self.collector.add(
                checker=self.checker, rule_id="format.page.size",
                severity=page["size"]["severity"],
                message=f"第 {', '.join(map(str, bad_pages[:5]))} 页纸张非标准 A4（{ew}×{eh}mm）",
                suggestion="确认源文档纸张设置为 A4 后重新导出 PDF",
                location={"pages": bad_pages[:5]},
            )

        # PDF 无法可靠还原页边距/字体/段落格式
        for rule in ("format.page.margin", "format.font.body", "format.font.size",
                     "format.paragraph.indent"):
            self.collector.note_skipped(rule)

        if self.rules["heading"].get("enabled", True):
            lines: list[str] = []
            for text in page_texts:
                lines.extend(text.splitlines())
            self._check_heading_sequence(lines, location_kind="page")

    # ---------------- 标题层级（docx/pdf 共用） ----------------

    def _check_heading_sequence(self, lines: list[str], *, location_kind: str) -> None:
        seen_levels: set[int] = set()
        for idx, raw in enumerate(lines):
            text = raw.strip()
            if not text:
                continue
            level = None
            for lv, pat in HEADING_PATTERNS:
                if pat.match(text):
                    level = lv
                    break
            if level is None:
                continue
            if seen_levels and level > max(seen_levels) + 1:
                missing = "/".join(
                    {1: "一、", 2: "（一）", 3: "1.", 4: "（1）"}[lv]
                    for lv in range(max(seen_levels) + 1, level)
                )
                location = (
                    {"paragraph_index": idx, "snippet": text[:30]}
                    if location_kind == "paragraph"
                    else {"line_index": idx, "snippet": text[:30]}
                )
                self.collector.add(
                    checker=self.checker, rule_id="format.heading.sequence",
                    severity=self.rules["heading"]["severity"],
                    message=f"标题层级可能跳级：「{text[:24]}」前缺少 {missing} 层级",
                    suggestion="按 一、 → （一） → 1. → （1） 的顺序编排标题",
                    location=location,
                )
            seen_levels.add(level)
