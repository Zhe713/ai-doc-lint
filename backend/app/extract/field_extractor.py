"""字段抽取器（W5 Day22）。

两级抽取，token 只花在规则抽不到的字段上：
1. 规则层（0 token）：字段规则包中的正则按序匹配，按类型归一化（金额统一折算为元）；
2. LLM 补抽层：规则未命中的字段打包（每批 6 个）请求 LLM，强制 JSON；
   LLM 给出的原文引用必须能在文本中匹配，匹配不上直接丢弃（反幻觉护栏）。

结果 upsert 进 document_fields 表。
"""

import json
import logging
import re
from datetime import datetime

from app.checkers.loader import load_field_pack
from app.db import storage
from app.llm.client import LLMCallError, LLMNotConfiguredError, chat
from app.models.document import (
    FIELD_DATE,
    FIELD_MONEY,
    FIELD_NUMBER,
    FIELD_PERCENT,
    FIELD_SOURCE_LLM,
    FIELD_SOURCE_RULE,
    Artifact,
    Document,
    DocumentField,
)

log = logging.getLogger("extract")

FIELDS_PER_BATCH = 6
LLM_CONFIDENCE = 0.7


class FieldExtractor:
    def __init__(self, db, document: Document, *, allow_llm: bool = True):
        self.db = db
        self.document = document
        self.allow_llm = allow_llm
        self.text = ""
        self.warnings: list[str] = []

    def run(self) -> list[DocumentField]:
        artifact = (
            self.db.query(Artifact)
            .filter(Artifact.document_id == self.document.id,
                    Artifact.kind == "plaintext")
            .one_or_none()
        )
        if artifact is None:
            return []

        pack = load_field_pack(self.document.doc_type)
        if not pack:
            return []

        self.text = storage.get_object_bytes(
            artifact.storage_key
        ).decode("utf-8", errors="replace")

        out: list[DocumentField] = []
        missing: list[dict] = []
        for spec in pack:
            field = self._rule_extract(spec)
            if field is None:
                missing.append(spec)
            else:
                out.append(field)

        if missing and self.allow_llm:
            out.extend(self._llm_extract(missing))

        self.db.flush()
        return out

    # ---------------- 规则层 ----------------

    def _rule_extract(self, spec: dict) -> DocumentField | None:
        for pattern in spec["patterns"]:
            m = re.search(pattern, self.text)
            if not m:
                continue
            raw = m.group(1).strip()
            if not raw:
                continue
            # 字符串字段只取首行，避免吞掉后续段落
            if spec["type"] == "string":
                raw = raw.splitlines()[0].strip()
            field = self._build_field(
                spec, raw, source=FIELD_SOURCE_RULE, confidence=1.0,
                location={"start": m.start(1),
                          "snippet": self.text[max(0, m.start(1) - 20):
                                              m.end(1) + 20].strip()[:80]},
                unit=m.group(2) if m.lastindex and m.lastindex >= 2 else None,
            )
            if field is not None:
                return self._upsert(field)
        return None

    def _build_field(
        self, spec: dict, raw: str, *, source: str, confidence: float,
        location: dict | None, unit: str | None,
    ) -> DocumentField | None:
        value_type = spec["type"]
        field = DocumentField(
            document_id=self.document.id,
            field_key=spec["key"],
            field_label=spec["label"],
            value_type=value_type,
            value_text=raw,
            confidence=confidence,
            source=source,
            location=location,
        )
        try:
            if value_type in (FIELD_NUMBER, FIELD_PERCENT):
                field.value_number = float(raw.replace(",", ""))
            elif value_type == FIELD_MONEY:
                yuan = float(raw.replace(",", ""))
                if unit and "万" in unit:
                    yuan *= 10000
                field.value_number = yuan
            elif value_type == FIELD_DATE:
                field.value_date = parse_date(raw)
                if field.value_date is None:
                    return None
        except (ValueError, AttributeError):
            return None
        return field

    # ---------------- LLM 补抽层 ----------------

    def _llm_extract(self, missing: list[dict]) -> list[DocumentField]:
        result: list[DocumentField] = []
        for offset in range(0, len(missing), FIELDS_PER_BATCH):
            group = missing[offset:offset + FIELDS_PER_BATCH]
            prompt = self._build_prompt(group)
            try:
                resp = chat(
                    [{"role": "user", "content": prompt}],
                    scene="field_extract", json_mode=True, temperature=0.0,
                )
                items = self._parse(resp.content, group)
                if items is None:
                    resp = chat(
                        [{"role": "user", "content": prompt
                          + "\n（上次输出无法解析，请严格只输出指定 JSON）"}],
                        scene="field_extract", json_mode=True,
                        temperature=0.0,
                    )
                    items = self._parse(resp.content, group)
                if items is None:
                    self.warnings.append(
                        f"{len(group)} 个字段 LLM 输出无法解析，未予抽取")
                    continue
            except (LLMNotConfiguredError, LLMCallError) as exc:
                self.warnings.append(
                    f"字段补抽未能调用 LLM：{type(exc).__name__}")
                return result

            seen_keys: set[str] = set()
            for item in items:
                key = item.get("key")
                if key in seen_keys:
                    # LLM 可能对同一字段输出多条（大小写/措辞不同）：取第一条
                    continue
                seen_keys.add(key)
                spec = next((s for s in group
                             if s["key"] == key), None)
                if spec is None:
                    continue
                value = (item.get("value") or "").strip()
                quote = (item.get("quote") or "").strip()
                if not value:
                    continue
                if not self._quote_matches(quote):
                    # 引用无法在原文匹配：疑似幻觉，丢弃
                    self.warnings.append(
                        f"字段 {spec['key']} 的 LLM 引用无法在原文匹配，已丢弃")
                    continue
                field = self._build_field(
                    spec, value, source=FIELD_SOURCE_LLM,
                    confidence=LLM_CONFIDENCE,
                    location={"snippet": quote[:80]}, unit=None,
                )
                if field is not None:
                    result.append(self._upsert(field))
        return result

    def _build_prompt(self, group: list[dict]) -> str:
        lines = [
            "你是文档信息抽取助手。请从给定文档原文中抽取下列字段。",
            "只能依据原文，不得推测或编造；原文确实没有的字段请直接省略。",
            "只输出 JSON，格式："
            '{"fields":[{"key":"字段key","value":"字段值",'
            '"quote":"包含该字段的原文短句"}]}',
            "金额请保留原文的数字与单位；日期保留原文写法。",
            "",
            "【文档原文】",
            self.text[:12000],
            "",
            "【待抽取字段】",
        ]
        for spec in group:
            lines.append(f'- key={spec["key"]} 名称={spec["label"]}')
        return "\n".join(lines)

    @staticmethod
    def _parse(content: str, group: dict):
        try:
            data = json.loads(content)
            fields = data["fields"]
            assert isinstance(fields, list)
            keys = {s["key"] for s in group}
            for item in fields:
                assert item["key"] in keys
            return fields
        except Exception:  # noqa: BLE001
            return None

    def _quote_matches(self, quote: str) -> bool:
        if not quote:
            return False
        if quote in self.text:
            return True
        collapsed = "".join(self.text.split())
        return "".join(quote.split()) in collapsed

    # ---------------- 入库 ----------------

    def _upsert(self, field: DocumentField) -> DocumentField:
        existing = (
            self.db.query(DocumentField)
            .filter(DocumentField.document_id == self.document.id,
                    DocumentField.field_key == field.field_key)
            .one_or_none()
        )
        if existing is None:
            self.db.add(field)
            return field
        existing.field_label = field.field_label
        existing.value_type = field.value_type
        existing.value_text = field.value_text
        existing.value_number = field.value_number
        existing.value_date = field.value_date
        existing.confidence = field.confidence
        existing.source = field.source
        existing.location = field.location
        return existing


_DATE_PATTERNS = (
    ("%Y-%m-%d", re.compile(r"\d{4}-\d{1,2}-\d{1,2}")),
    ("%Y/%m/%d", re.compile(r"\d{4}/\d{1,2}/\d{1,2}")),
    ("%Y年%m月%d日", re.compile(r"\d{4}年\d{1,2}月\d{1,2}日?")),
)


def parse_date(raw: str) -> datetime | None:
    for fmt, pattern in _DATE_PATTERNS:
        m = pattern.search(raw)
        if m:
            try:
                return datetime.strptime(m.group(0), fmt)
            except ValueError:
                continue
    return None
