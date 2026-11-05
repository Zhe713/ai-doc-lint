"""错别字检查器（上下文复核版）。

两阶段，准确性优先：
1. 本地引擎（pycorrector ngram，失败降级混淆集）高召回产出候选，0 token；
2. 全部候选按上下文窗口分批送 LLM 逐词裁决——只有结合语境确认是真错才出 finding，
   「由其所在单位」这类合法用法在复核阶段被拦截，不再产生无上下文误报。

反幻觉护栏：LLM 确认的错词必须与原文定位一致，否则丢弃该条。
LLM 不可用时不直接报本地候选（避免误报），记 warning 并 skip。
"""

import functools
import json
import logging
import re

from app.checkers.loader import RULES_DIR
from app.db import storage
from app.llm.client import (
    LLMCallError,
    LLMNotConfiguredError,
    LLMQuotaExceededError,
    chat,
)
from app.models.document import (
    CHECKER_TYPO,
    FINDING_SOURCE_HYBRID,
    Document,
)

log = logging.getLogger("checker.typo")

MAX_FINDINGS = 50
CANDIDATES_PER_BATCH = 8
CONTEXT_CHARS = 120
SENTENCE_BREAKS = "。；！？\n"

# 汉语里「介词/连词 + 其」是恒合法的结构（由其、因其、对其、以其、就其……），
# 本地混淆集却把「由其」列成「尤其」的候选——这是最典型的无上下文误报。
# 这一层在进 LLM 之前就拦掉，既省 token，也避免模型偶尔「顺着候选走」。
_LEGAL_PREFIX_ITS = re.compile(
    r"^(由|因|对|以|就|向|与|和|及|从|把|被|给|同|替|为|在|至|按|依|据|经|除)其$"
)
# 「X 以」类固定搭配（予以/加以/给以…），同样不是错别字
_LEGAL_FIXED = frozenset({"予以", "加以", "给以", "藉以", "得以", "所以", "加以"})
# 合同里高频的合法双字词，混淆集常与之互斥（如 定金/订金 各有法义，不可互改）
_LEGAL_TERMS = frozenset({
    "定金", "订金", "押金", "价款", "给付", "瑕疵", "孳息", "抗辩", "抵销",
    "标的", "承诺", "要约", "违约责任", "不可抗力", "救济", "除斥期间",
})


def _is_legal_usage(word: str) -> bool:
    """候选词本身是否为汉语/合同中的合法表达（是 → 不可能是错别字）。"""
    w = (word or "").strip()
    if not w:
        return False
    if w in _LEGAL_FIXED or w in _LEGAL_TERMS:
        return True
    return bool(_LEGAL_PREFIX_ITS.match(w))


@functools.lru_cache(maxsize=1)
def _load_whitelist() -> tuple[str, ...]:
    """合并加载内置白名单 + W7 自动扩充白名单（auto 文件可一键回滚）。"""
    words: list[str] = []
    for name in ("typo_whitelist.txt", "typo_whitelist_auto.txt"):
        path = RULES_DIR / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line)
    return tuple(words)


def _normalize_errors(result) -> list[tuple[str, str, int, int]]:
    """兼容 pycorrector 返回：dict / (text, errors)；error 为 4 元组或 3 元组。"""
    if isinstance(result, dict):
        errors = result.get("errors", [])
    elif isinstance(result, (tuple, list)) and len(result) == 2:
        errors = result[1]
    else:
        errors = []
    out = []
    for e in errors:
        if len(e) >= 4:
            wrong, right, start, end = e[0], e[1], int(e[2]), int(e[3])
        elif len(e) == 3:
            wrong, right, start = e[0], e[1], int(e[2])
            end = start + len(wrong)
        else:
            continue
        out.append((wrong, right, start, end))
    return out


@functools.lru_cache(maxsize=1)
def _get_engine() -> tuple[object, str]:
    """返回 (engine, mode)；mode = ngram / confusion / unavailable。进程内单例。"""
    try:
        import pycorrector

        probe = pycorrector.correct("因该让坐")  # kenlm 缺失/模型下载失败会在此抛错
        _normalize_errors(probe)
        return pycorrector, "ngram"
    except Exception as exc:  # noqa: BLE001
        log.warning("ngram 引擎不可用，降级混淆集模式: %s", exc)
        try:
            from pycorrector import ConfusionCorrector

            engine = ConfusionCorrector(
                custom_confusion_path_or_dict=str(RULES_DIR / "typo_confusion.txt")
            )
            return engine, "confusion"
        except Exception as exc2:  # noqa: BLE001
            log.error("混淆集引擎不可用: %s", exc2)
            return None, "unavailable"


class TypoChecker:
    checker = CHECKER_TYPO

    def __init__(self, db, document: Document, collector, review_options=None):
        self.db = db
        self.document = document
        self.collector = collector
        self.ext = (document.ext or "").lower()

    def run(self) -> None:
        from app.models.document import Artifact

        artifact = (
            self.db.query(Artifact)
            .filter(Artifact.document_id == self.document.id, Artifact.kind == "plaintext")
            .order_by(Artifact.created_at.desc())
            .first()
        )
        if artifact is None:
            self.collector.note_skipped("typo.correction")
            return

        engine, mode = _get_engine()
        if engine is None:
            self.collector.add_warning("错别字模型不可用，本次未执行错别字检查（请检查模型安装）")
            self.collector.note_skipped("typo.correction")
            return
        if mode == "confusion":
            self.collector.add_warning("错别字本地引擎运行在混淆集模式，候选覆盖范围较有限，已由 LLM 上下文复核")

        text = storage.get_object_bytes(artifact.storage_key).decode("utf-8", errors="replace")

        try:
            errors = _normalize_errors(engine.correct(text))
        except Exception as exc:  # noqa: BLE001
            log.warning("错别字候选生成失败: %s", exc)
            self.collector.add_warning(f"错别字检查执行异常：{type(exc).__name__}")
            return

        protected = self._protected_spans(text)
        raw_count = len(errors)
        errors = [e for e in errors if not self._overlaps(e, protected) and not _is_legal_usage(e[0])]
        legal_dropped = raw_count - len(errors)
        if legal_dropped:
            log.info("typo 合法用法/白名单直接拦截 %d 处，不进入 LLM 复核", legal_dropped)
        if not errors:
            return

        try:
            verdicts = self._verify_with_llm(text, errors[:MAX_FINDINGS])
        except LLMQuotaExceededError as exc:
            self.collector.add_warning(f"{exc}；本次未输出错别字结论")
            self.collector.note_skipped("typo.correction")
            return
        except (LLMNotConfiguredError, LLMCallError) as exc:
            # LLM 不可用：不直接报未经上下文复核的本地候选，避免误报
            self.collector.add_warning(
                f"错别字上下文复核未能调用 LLM（{type(exc).__name__}），本次未输出错别字结论"
            )
            self.collector.note_skipped("typo.correction")
            return

        confirmed = 0
        for cand, verdict in zip(errors[:MAX_FINDINGS], verdicts):
            wrong, right, start, end = cand
            if not verdict or not verdict.get("is_error"):
                continue  # 上下文判定为合法用法，拦截误报
            # 双保险：即便模型误判，命中合法结构也一律不报
            if _is_legal_usage(wrong):
                log.info("typo 拦截模型误判的合法用法：%s", wrong)
                continue
            correction = (verdict.get("correction") or right or "").strip()
            # 反幻觉护栏：原文定位必须与候选错词一致
            if text[start:end] != wrong:
                continue
            # 纠错结果不能与原文相同，否则是空纠错
            if not correction or correction == wrong:
                continue
            paragraph = text.count("\n", 0, start)
            reason = (verdict.get("reason") or "").strip()
            self.collector.add(
                checker=self.checker, rule_id="typo.correction",
                severity="warning",
                message=f"疑似错别字：「{wrong}」建议改为「{correction}」",
                suggestion=f"将「{wrong}」替换为「{correction}」",
                location={
                    "start": start, "end": end, "paragraph_index": paragraph,
                    # 展示整句，读者才能自己判断对错（此前只截 ±8 字，看不懂上下文）
                    "snippet": self._sentence_context(text, start, end),
                    "wrong": wrong,
                    "correction": correction,
                },
                source=FINDING_SOURCE_HYBRID,
                llm_reason=reason or None,
                llm_model=getattr(self, "_llm_model", None),
            )
            confirmed += 1
        if len(errors) > MAX_FINDINGS:
            self.collector.add_warning(
                f"疑似错别字候选共 {len(errors)} 处，仅复核前 {MAX_FINDINGS} 处"
            )
        log.info("typo 候选 %d，LLM 确认 %d", len(errors), confirmed)

    # ---------------- LLM 上下文复核 ----------------

    @staticmethod
    def _sentence_context(text: str, start: int, end: int, cap: int = 60) -> str:
        """取候选词所在的整句（以句号/分号/换行为界），最多左右各 cap 字。

        交给用户的是能独立读懂的完整句子，而不是 ±8 字的碎片。
        """
        left = 0
        for i in range(start - 1, max(start - 200, -1), -1):
            if text[i] in SENTENCE_BREAKS:
                left = i + 1
                break
        right = len(text)
        for i in range(end, min(end + 200, len(text))):
            if text[i] in SENTENCE_BREAKS:
                right = i + 1
                break
        left = max(left, start - cap)
        right = min(right, end + cap)
        return text[left:right].strip()

    def _build_prompt(self, text: str, batch: list[tuple]) -> str:
        lines = [
            "你是中文合同校对助手。下面给出若干候选错词及其所在上下文，",
            "请逐个判断该词在当前语境下是否真的是错别字。",
            "",
            "判断规则（必须遵守）：",
            "1. 只要能读通、符合汉语语法或合同惯用表达，就不是错别字——宁可放过，不可误报。",
            "2. 「由其／因其／对其／以其／予以／加以」这类「介词+其/以」结构完全合法，不是错别字。",
            "3. 同音字只有在语义不通时才算错（如「签定」应为「签订」、「权力义务」应为「权利义务」）。",
            "4. 判断不了、上下文不足，一律判 is_error=false，不要猜。",
            "",
            "只输出 JSON："
            '{"verdicts":[{"index":序号,"is_error":true或false,'
            '"correction":"正确写法，不是错误时为空字符串","reason":"不超过30字，说明为什么错/为什么不改"}]}',
            "",
        ]
        for i, (wrong, right, start, end) in enumerate(batch):
            ctx = self._sentence_context(text, start, end, cap=CONTEXT_CHARS)
            lines.append(
                f"{i}. 候选词「{wrong}」（本地建议「{right}」）\n所在句子：{ctx}"
            )
        return "\n".join(lines)

    def _verify_with_llm(self, text: str, errors: list[tuple]) -> list[dict | None]:
        verdicts: list[dict | None] = []
        for offset in range(0, len(errors), CANDIDATES_PER_BATCH):
            batch = errors[offset:offset + CANDIDATES_PER_BATCH]
            prompt = self._build_prompt(text, batch)
            resp = chat(
                [{"role": "user", "content": prompt}],
                scene="typo_verify", json_mode=True, temperature=0.0,
            )
            self._llm_model = getattr(resp, "model", None)
            parsed = self._parse(getattr(resp, "content", "") or "", len(batch))
            if parsed is None:
                resp = chat(
                    [{"role": "user", "content": prompt
                      + "\n（上次输出无法解析，请严格只输出指定 JSON）"}],
                    scene="typo_verify", json_mode=True, temperature=0.0,
                )
                self._llm_model = getattr(resp, "model", None) or self._llm_model
                parsed = self._parse(getattr(resp, "content", "") or "", len(batch))
            if parsed is None:
                self.collector.add_warning(
                    f"{len(batch)} 个错别字候选的 LLM 输出无法解析，该批未予判定"
                )
                verdicts.extend([None] * len(batch))
                continue
            by_index = {v.get("index"): v for v in parsed}
            for i in range(len(batch)):
                verdicts.append(by_index.get(i))
        return verdicts

    @staticmethod
    def _parse(content: str, batch_size: int):
        try:
            data = json.loads(content)
            verdicts = data["verdicts"]
            assert isinstance(verdicts, list)
            for v in verdicts:
                assert isinstance(v.get("is_error"), bool)
                assert isinstance(v.get("index"), int)
            return verdicts
        except Exception:  # noqa: BLE001
            return None

    # ---------------- 白名单 ----------------

    def _protected_spans(self, text: str) -> list[tuple[int, int]]:
        spans = []
        for word in _load_whitelist():
            start = text.find(word)
            while start != -1:
                spans.append((start, start + len(word)))
                start = text.find(word, start + 1)
        return spans

    @staticmethod
    def _overlaps(error, spans: list[tuple[int, int]]) -> bool:
        _, _, start, end = error
        for lo, hi in spans:
            if start < hi and end > lo:
                return True
        return False
