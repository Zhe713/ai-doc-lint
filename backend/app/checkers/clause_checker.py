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

        pack = load_clause_pack(self.document.doc_type)
        if not pack:
            self.collector.note_skipped("clause.check")
            return

        self.text = storage.get_object_bytes(
            artifact.storage_key
        ).decode("utf-8", errors="replace")

        missing, uncertain = self._prescreen(pack)
        for clause in missing:
            self._add_missing(clause, location=None)

        if uncertain:
            self._judge_with_llm(uncertain)

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
