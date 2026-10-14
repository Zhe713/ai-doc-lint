"""条款检查器（W4 Day17）。

三段判定，token 只花在真正存疑的条款上：
1. 规则预筛（0 token）：strong 命中=存在；strong/weak 均无=明确缺失（直接出 finding）；
   仅 weak 命中=存疑；
2. 存疑条款按弱信号窗口打包、分批 LLM 判定（强制 JSON，内容级失败重试一次）；
3. 反幻觉护栏：LLM 给出的原文引用必须能在文本中匹配，匹配不上丢弃定位并降级。

文档类型没有对应条款规则包时整体 skip，不产生误报。
"""

import json
import logging
import re

from app.checkers.loader import load_clause_pack
from app.db import storage
from app.llm.client import LLMCallError, LLMNotConfiguredError, chat
from app.models.document import CHECKER_CLAUSE, Artifact, Document

log = logging.getLogger("checker.clause")

CLAUSES_PER_BATCH = 4      # 每次 LLM 调用打包的存疑条款数
WINDOW_CHARS = 160         # 弱信号上下文窗口半径
MAX_WINDOW_PER_CLAUSE = 2  # 同一条款最多附带几个弱信号窗口

_DOWNGRADE = {"error": "warning", "warning": "info", "info": "info"}


class ClauseChecker:
    checker = CHECKER_CLAUSE

    def __init__(self, db, document: Document, collector, review_options=None):
        self.db = db
        self.document = document
        self.collector = collector
        self.text = ""

    def run(self) -> None:
        artifact = (
            self.db.query(Artifact)
            .filter(Artifact.document_id == self.document.id,
                    Artifact.kind == "plaintext")
            .one_or_none()
        )
        if artifact is None:
            self.collector.note_skipped("clause.check")
            return

        self.text = storage.get_object_bytes(
            artifact.storage_key
        ).decode("utf-8", errors="replace")

        # 金额大小写一致性勾稽：纯确定性、0 token（P1-4 修复）
        self._check_amount_consistency()

        pack = load_clause_pack(self.document.doc_type)
        if not pack:
            self.collector.note_skipped("clause.check")
            return

        missing, uncertain = self._prescreen(pack)
        for clause in missing:
            self._add_missing(clause, location=None)

        if uncertain:
            self._judge_with_llm(uncertain)

    # ---------------- 金额大小写勾稽（P1-4） ----------------

    _CN_DIGIT = {
        "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9,
        "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5,
        "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    }
    _CN_UNIT = {
        "十": 10, "拾": 10, "百": 100, "佰": 100,
        "千": 1000, "仟": 1000, "万": 10000, "萬": 10000,
        "亿": 100000000, "億": 100000000,
    }
    _CN_AMOUNT = re.compile(r"[壹贰叁肆伍陆柒捌玖拾佰仟万亿零]+(?:圆|元)")
    _DIGIT_AMOUNT = re.compile(r"(\d[\d,，.]*)\s*(?:万元|万圆|元|圆)")
    _AMOUNT_WINDOW = 200  # 大写金额与数字金额的配对搜索半径（字符）

    @classmethod
    def _cn_to_number(cls, s: str) -> float | None:
        total = 0.0
        section = 0.0
        number = 0.0
        for ch in s:
            if ch in cls._CN_DIGIT:
                number = float(cls._CN_DIGIT[ch])
            elif ch in cls._CN_UNIT:
                unit = cls._CN_UNIT[ch]
                if unit >= 10000:
                    section = (section + number) * unit
                    total += section
                    section = 0.0
                else:
                    section += (number if number else 1.0) * unit
                number = 0.0
            else:
                return None
        return total + section + number

    def _check_amount_consistency(self) -> None:
        cn_hits: list[tuple[float, int, str]] = []
        for m in self._CN_AMOUNT.finditer(self.text):
            num = self._cn_to_number(m.group(0)[:-1])
            if num is not None:
                cn_hits.append((num, m.start(), m.group(0)))
        if not cn_hits:
            return
        digit_hits: list[tuple[float, int, str]] = []
        for m in self._DIGIT_AMOUNT.finditer(self.text):
            raw = m.group(1).replace(",", "").replace("，", "")
            try:
                val = float(raw)
            except ValueError:
                continue
            if "万" in m.group(0):
                val *= 10000
            digit_hits.append((val, m.start(), m.group(0)))

        reported: set[int] = set()
        for cn_val, cn_pos, cn_text in cn_hits:
            best = min(
                digit_hits,
                key=lambda d: abs(d[1] - cn_pos),
                default=None,
            )
            if best is None or abs(best[1] - cn_pos) > self._AMOUNT_WINDOW:
                continue
            dig_val, dig_pos, dig_text = best
            if abs(dig_val - cn_val) < 0.01:
                continue
            key = cn_pos // 500
            if key in reported:
                continue
            reported.add(key)
            snippet = self.text[max(0, cn_pos - 40): cn_pos + 120]
            self.collector.add(
                checker=self.checker, rule_id="clause.amount.consistency",
                severity="error",
                message=(
                    f"金额大小写不一致：大写「{cn_text}」与小写「{dig_text}」不符"
                ),
                suggestion="核对合同金额，统一大小写后再签署",
                location={"snippet": snippet},
            )

    # ---------------- 规则预筛 ----------------

    @staticmethod
    def _first_hit(words: list[str], text: str) -> str | None:
        return next((w for w in words if w in text), None)

    def _prescreen(self, pack: list[dict]):
        missing: list[dict] = []
        uncertain: list[tuple[dict, str]] = []
        for clause in pack:
            if not clause.get("required", False):
                continue  # 可选条款缺失不报错
            if self._first_hit(clause["strong"], self.text):
                continue
            weak = self._first_hit(clause["weak"], self.text)
            if weak:
                uncertain.append((clause, weak))
            else:
                missing.append(clause)
        return missing, uncertain

    # ---------------- LLM 判定 ----------------

    def _windows(self, weak: str) -> str:
        windows: list[str] = []
        start = 0
        while len(windows) < MAX_WINDOW_PER_CLAUSE:
            idx = self.text.find(weak, start)
            if idx == -1:
                break
            windows.append(self.text[max(0, idx - WINDOW_CHARS):
                                    idx + len(weak) + WINDOW_CHARS])
            start = idx + len(weak)
        return "\n---\n".join(windows)

    def _build_prompt(self, group: list[tuple[dict, str]]) -> str:
        lines = [
            "你是文档条款审查助手。请判断下列条款在给定文本片段中是否真实存在。",
            "只能依据给定文本，不得推测；条款描述的核心内容真实出现才算存在。",
            "只输出 JSON，格式："
            '{"results":[{"id":"条款id","present":true或false,'
            '"quote":"能证明结论的原文短句，不存在时为空字符串",'
            '"reason":"不超过30字"}]}',
            "",
            "【文本片段】",
        ]
        for clause, weak in group:
            lines.append(f"〔围绕弱信号「{weak}」〕\n{self._windows(weak)}")
        lines.append("")
        lines.append("【待判定条款】")
        for i, (clause, weak) in enumerate(group, 1):
            lines.append(f"{i}. id={clause['id']} 名称={clause['name']}")
        return "\n".join(lines)

    def _judge_with_llm(self, uncertain: list[tuple[dict, str]]) -> None:
        for offset in range(0, len(uncertain), CLAUSES_PER_BATCH):
            group = uncertain[offset:offset + CLAUSES_PER_BATCH]
            prompt = self._build_prompt(group)
            try:
                resp = chat(
                    [{"role": "user", "content": prompt}],
                    scene="clause", json_mode=True, temperature=0.1,
                )
                parsed = self._parse(resp.content, group)
                if parsed is None:
                    # 内容级重试一次：提示模型严格输出
                    resp = chat(
                        [{"role": "user", "content": prompt
                          + "\n（上次输出无法解析，请严格只输出指定 JSON）"}],
                        scene="clause", json_mode=True, temperature=0.0,
                    )
                    parsed = self._parse(resp.content, group)
                if parsed is None:
                    self.collector.add_warning(
                        f"{len(group)} 个存疑条款 LLM 输出无法解析，未予判定"
                    )
                    continue
            except (LLMNotConfiguredError, LLMCallError) as exc:
                self.collector.add_warning(
                    f"存疑条款未能调用 LLM 判定：{type(exc).__name__}"
                )
                return

            by_id = {item["id"]: item for item in parsed}
            for clause, _ in group:
                item = by_id.get(clause["id"])
                if item is None:
                    self.collector.add_warning(
                        f"条款 {clause['id']} 未获 LLM 判定结果"
                    )
                    continue
                if item.get("present"):
                    continue
                self._apply_llm_missing(clause, item.get("quote", ""))

    @staticmethod
    def _parse(content: str, group):
        try:
            data = json.loads(content)
            results = data["results"]
            assert isinstance(results, list)
            ids = {c["id"] for c, _ in group}
            for item in results:
                assert item["id"] in ids
                assert isinstance(item["present"], bool)
            return results
        except Exception:  # noqa: BLE001  JSON 结构任何不合法都触发重试
            return None

    # ---------------- findings ----------------

    def _add_missing(self, clause: dict, *, location: dict | None) -> None:
        self.collector.add(
            checker=self.checker, rule_id=clause["id"],
            severity=clause["severity"],
            message=f"缺少必要条款：{clause['name']}",
            suggestion=f"请补充「{clause['name']}」相关约定",
            location=location,
        )

    def _apply_llm_missing(self, clause: dict, quote: str) -> None:
        severity = clause["severity"]
        location = None
        quote = (quote or "").strip()
        if quote:
            # 空白字符不敏感匹配（原文换行/空格差异）
            collapsed = "".join(self.text.split())
            if quote in self.text:
                location = {"snippet": quote[:60]}
            elif "".join(quote.split()) in collapsed:
                location = {"snippet": quote[:60]}
            else:
                # 引用在原文中找不到：疑似幻觉，丢弃定位并降级
                location = None
                severity = _DOWNGRADE.get(severity, "info")
                self.collector.add_warning(
                    f"条款 {clause['id']} 的 LLM 引用无法在原文匹配，已降级处理"
                )
        self.collector.add(
            checker=self.checker, rule_id=clause["id"],
            severity=severity,
            message=f"缺少必要条款：{clause['name']}",
            suggestion=f"请补充「{clause['name']}」相关约定",
            location=location,
        )
