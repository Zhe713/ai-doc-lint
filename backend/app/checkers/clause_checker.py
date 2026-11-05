"""条款检查器（LLM 全量确认版）。

三类判定路径：
- 强信号关键词命中 → 直接判定存在（确定性，source=rule，0 token）；
- 弱信号命中 → 打包上下文窗口送 LLM 判定（source=hybrid）；
- 无任何关键词命中 → 不再直接判缺失，而是把条款定义与文档章节结构送 LLM
  做语义确认，只有确认整份文档确实没有该条款才报缺失（source=llm），
  避免“换了个说法/同义词”导致的误报。

反幻觉护栏：LLM 给出的引用必须能在原文匹配，匹配不上则丢弃定位并降级。
金额大小写勾稽为确定性规则，不依赖 LLM。
"""

import json
import logging
import re

from app.checkers.loader import load_clause_pack
from app.db import storage
from app.llm.client import (
    LLMCallError,
    LLMNotConfiguredError,
    LLMQuotaExceededError,
    chat,
)
from app.models.document import (
    CHECKER_CLAUSE,
    FINDING_SOURCE_HYBRID,
    FINDING_SOURCE_LLM,
    FINDING_SOURCE_RULE,
    Document,
)

log = logging.getLogger("checker.clause")

CLAUSES_PER_BATCH = 4
WINDOW_CHARS = 160
MAX_WINDOW_PER_CLAUSE = 2
_AMOUNT_WINDOW = 200
_DOWNGRADE = {"error": "warning", "warning": "info", "info": "info"}


class ClauseChecker:
    checker = CHECKER_CLAUSE

    def __init__(self, db, document: Document, collector, review_options=None):
        self.db = db
        self.document = document
        self.collector = collector
        self.text = ""
        self._llm_model = None

    def run(self) -> None:
        from app.models.document import Artifact

        # OCR 重试会写入多份 plaintext 产物，必须取最新一份；
        # 早期用 one_or_none() 在存在多份时会抛 MultipleResultsFound，导致整块条款检查失败。
        artifact = (
            self.db.query(Artifact)
            .filter(Artifact.document_id == self.document.id,
                    Artifact.kind == "plaintext")
            .order_by(Artifact.created_at.desc())
            .first()
        )
        if artifact is None:
            self.collector.note_skipped("clause.check")
            return

        self.text = storage.get_object_bytes(
            artifact.storage_key
        ).decode("utf-8", errors="replace")

        # 金额大小写一致性勾稽：纯确定性、0 token
        self._check_amount_consistency()

        pack = load_clause_pack(self.document.doc_type, str(self.document.user_id))
        if not pack:
            self.collector.note_skipped("clause.check")
            return

        present, uncertain, missing = self._prescreen(pack)
        log.info("clause prescreen: present=%d uncertain=%d missing=%d",
                 len(present), len(uncertain), len(missing))

        try:
            self._judge_uncertain(uncertain)
            self._confirm_missing(missing)
        except LLMQuotaExceededError as exc:
            # 额度耗尽：规则判定结果照常输出，只是深度复核暂停 —— 必须说清是额度问题
            self.collector.add_warning(
                f"{exc}；条款弱信号与缺失项未做 AI 复核"
            )
            for clause, _ in uncertain:
                self.collector.note_skipped(clause["id"])
            for clause in missing:
                self.collector.note_skipped(clause["id"])
        except (LLMNotConfiguredError, LLMCallError) as exc:
            self.collector.add_warning(
                f"条款 LLM 判定不可用（{type(exc).__name__}）：弱信号与缺失项未输出结论"
            )
            for clause, _ in uncertain:
                self.collector.note_skipped(clause["id"])
            for clause in missing:
                self.collector.note_skipped(clause["id"])

    # ---------------- 规则预筛 ----------------

    @staticmethod
    def _first_hit(words: list[str], text: str) -> str | None:
        return next((w for w in words if w in text), None)

    def _prescreen(self, pack: list[dict]):
        present: list[str] = []
        uncertain: list[tuple[dict, str]] = []
        missing: list[dict] = []
        for clause in pack:
            if not clause.get("required", False):
                continue  # 可选条款缺失不报错
            if self._first_hit(clause["strong"], self.text):
                present.append(clause["id"])
                continue
            weak = self._first_hit(clause["weak"], self.text)
            if weak:
                uncertain.append((clause, weak))
            else:
                missing.append(clause)
        return present, uncertain, missing

    # ---------------- 弱信号 LLM 判定 ----------------

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

    def _build_uncertain_prompt(self, group: list[tuple[dict, str]]) -> str:
        lines = [
            "你是文档条款审查助手。请判断下列条款在给定文本片段中是否真实存在且完整。",
            "只能依据给定文本，不得推测；核心内容真实出现才算存在。",
            "status 只能取 present（存在且完整）、missing（缺失或实质不完整）、uncertain（无法判断）。",
            "只输出 JSON：{\"results\":[{\"clause_id\":\"...\",\"status\":\"...\","
            "\"quote\":\"能证明结论的原文短句，不存在为空\",\"reason\":\"不超过30字\"}]}",
            "",
            "【文本片段】",
        ]
        for clause, weak in group:
            lines.append(f"〔围绕弱信号「{weak}」〕\n{self._windows(weak)}")
        lines.append("")
        lines.append("【待判定条款】")
        for i, (clause, _) in enumerate(group, 1):
            lines.append(f"{i}. id={clause['id']} 名称={clause['name']}")
        return "\n".join(lines)

    def _judge_uncertain(self, uncertain: list[tuple[dict, str]]) -> None:
        for offset in range(0, len(uncertain), CLAUSES_PER_BATCH):
            group = uncertain[offset:offset + CLAUSES_PER_BATCH]
            prompt = self._build_uncertain_prompt(group)
            results = self._chat_json(prompt, scene="clause", temperature=0.1)
            if results is None:
                for clause, _ in group:
                    self.collector.add_warning(
                        f"条款 {clause['id']} 的 LLM 输出无法解析，未予判定"
                    )
                    self.collector.note_skipped(clause["id"])
                continue
            by_id = {r.get("clause_id"): r for r in results}
            for clause, _ in group:
                result = by_id.get(clause["id"])
                if result is None or result.get("status") != "missing":
                    continue
                self._apply_uncertain_missing(clause, (result.get("quote") or "").strip(),
                                              (result.get("reason") or "").strip())

    def _apply_uncertain_missing(self, clause: dict, quote: str, reason: str) -> None:
        severity = clause["severity"]
        location = None
        if quote:
            matched, location = self._match_quote(quote)
            if not matched:
                severity = _DOWNGRADE.get(severity, "info")
                self.collector.add_warning(
                    f"条款 {clause['id']} 的 LLM 引用无法在原文匹配，已降级处理"
                )
        self.collector.add(
            checker=self.checker, rule_id=clause["id"], severity=severity,
            message=f"「{clause['name']}」条款存在但表述不完整或不规范",
            suggestion=f"请补充完善「{clause['name']}」相关约定",
            location=location,
            source=FINDING_SOURCE_HYBRID,
            llm_reason=reason or None,
            llm_model=self._llm_model,
        )

    # ---------------- 缺失项 LLM 语义确认 ----------------

    def _confirm_missing(self, missing: list[dict]) -> None:
        headings = self._extract_headings()
        for offset in range(0, len(missing), CLAUSES_PER_BATCH):
            group = missing[offset:offset + CLAUSES_PER_BATCH]
            prompt = self._build_missing_prompt(group, headings)
            results = self._chat_json(prompt, scene="clause_missing", temperature=0.0)
            if results is None:
                for clause in group:
                    self.collector.add_warning(
                        f"条款 {clause['id']} 的缺失确认无法解析，未予判定"
                    )
                    self.collector.note_skipped(clause["id"])
                continue
            by_id = {r.get("clause_id"): r for r in results}
            for clause in group:
                result = by_id.get(clause["id"])
                if result is None or result.get("status") == "present":
                    continue  # 语义上找到同义/改写条款，不判缺失
                reason = (result.get("reason") or "").strip()
                self.collector.add(
                    checker=self.checker, rule_id=clause["id"],
                    severity=clause["severity"],
                    message=f"缺少必要条款：{clause['name']}",
                    suggestion=f"请补充「{clause['name']}」相关约定",
                    location=None,
                    source=FINDING_SOURCE_LLM,
                    llm_reason=reason or None,
                    llm_model=self._llm_model,
                )

    def _build_missing_prompt(self, group: list[dict], headings: list[str]) -> str:
        lines = [
            "你是合同审查助手。以下条款在文档中未命中任何预设关键词。",
            "请基于文档章节标题判断是否存在语义相同或相近的条款（允许同义词、不同表述）。",
            "status 取 present（能找到对应章节）或 absent（确实没有）。",
            "只输出 JSON：{\"results\":[{\"clause_id\":\"...\",\"status\":\"present/absent\","
            "\"quote\":\"匹配到的标题，没有为空\",\"reason\":\"不超过30字\"}]}",
            "",
            "文档章节标题：",
        ]
        lines.extend(f"- {h}" for h in headings[:120])
        lines.append("")
        lines.append("【待确认条款】")
        for i, c in enumerate(group, 1):
            lines.append(
                f"{i}. id={c['id']} 名称={c['name']}（强关键词 {c['strong']}；弱关键词 {c['weak']}）"
            )
        return "\n".join(lines)

    def _extract_headings(self) -> list[str]:
        heading_re = re.compile(
            r"^\s*(第[一二三四五六七八九十百]+条|[一二三四五六七八九十]+、|"
            r"（[一二三四五六七八九十]+）|\d+[.、])"
        )
        out = []
        for line in self.text.splitlines():
            s = line.strip()
            if 2 <= len(s) <= 40 and heading_re.match(s):
                out.append(s)
        return out

    # ---------------- 反幻觉护栏 ----------------

    def _match_quote(self, quote: str) -> tuple[bool, dict | None]:
        quote = (quote or "").strip()
        if not quote:
            return False, None
        if quote in self.text:
            return True, {"snippet": quote[:60]}
        if "".join(quote.split()) in "".join(self.text.split()):
            return True, {"snippet": quote[:60]}
        return False, None

    # ---------------- 金额大小写一致性（确定性） ----------------

    _CN_DIGIT = {
        "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9,
        "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5,
        "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    }
    _CN_UNIT = {
        "十": 10, "拾": 10, "百": 100, "佰": 100,
        "千": 1000, "仟": 1000,
        "万": 10000, "萬": 10000,
        "亿": 100000000, "億": 100000000,
    }
    _CN_AMOUNT = re.compile(r"[壹贰叁肆伍陆柒捌玖拾佰仟万亿零]+(?:圆|元)")
    _DIGIT_AMOUNT = re.compile(r"(\d[\d,，.]*)\s*(?:万元|万圆|元|圆)")

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
            best = min(digit_hits, key=lambda d: abs(d[1] - cn_pos), default=None)
            if best is None or abs(best[1] - cn_pos) > _AMOUNT_WINDOW:
                continue
            dig_val, _, dig_text = best
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
                message=f"金额大小写不一致：大写「{cn_text}」与小写「{dig_text}」不符",
                suggestion="核对合同金额，统一大小写后再签署",
                location={"snippet": snippet},
                source=FINDING_SOURCE_RULE,
            )

    # ---------------- LLM 调用与解析 ----------------

    def _chat_json(self, prompt: str, *, scene: str, temperature: float):
        resp = chat(
            [{"role": "user", "content": prompt}],
            scene=scene, json_mode=True, temperature=temperature,
        )
        # 兼容：生产实现返回 LLMResult（带 .model/.content），
        # 测试桩可能返回 SimpleNamespace 甚至 None，这里都不应抛异常。
        self._llm_model = getattr(resp, "model", None)
        parsed = self._parse(getattr(resp, "content", "") or "")
        if parsed is None:
            resp = chat(
                [{"role": "user", "content": prompt
                  + "\n（上次输出无法解析，请严格只输出指定 JSON）"}],
                scene=scene, json_mode=True, temperature=0.0,
            )
            self._llm_model = getattr(resp, "model", None) or self._llm_model
            parsed = self._parse(getattr(resp, "content", "") or "")
        return parsed

    @staticmethod
    def _parse(content: str):
        try:
            data = json.loads(content)
            results = data["results"]
            assert isinstance(results, list)
            for r in results:
                assert r.get("clause_id") and r.get("status")
            return results
        except Exception:  # noqa: BLE001
            return None
