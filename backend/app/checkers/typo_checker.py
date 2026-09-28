"""错别字检查器（W3 Day13）。

- 优先 pycorrector kenlm ngram（本地模型，0 token）；模型/依赖缺失 → 内置混淆集模式并告警；
- 混淆集模式：ConfusionCorrector + ahocorasick 多模匹配，数据为 rules/typo_confusion.txt；
- 合同/商务术语白名单（typo_whitelist.txt），行家术语不报错；
- 字符级 offset 定位（相对 plaintext），标注段落与片段；
- 问题数上限保护，超出部分计入 stats 但不刷屏。
"""

import functools
import logging

from app.checkers.loader import RULES_DIR
from app.db import storage
from app.models.document import CHECKER_TYPO, Document

log = logging.getLogger("checker.typo")

MAX_FINDINGS = 50


@functools.lru_cache(maxsize=1)
def _load_whitelist() -> tuple[str, ...]:
    path = RULES_DIR / "typo_whitelist.txt"
    words = []
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
            .one_or_none()
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
            self.collector.add_warning("错别字检查运行在混淆集模式（ngram 模型未就绪），覆盖范围较有限")

        text = storage.get_object_bytes(artifact.storage_key).decode("utf-8", errors="replace")

        try:
            errors = _normalize_errors(engine.correct(text))
        except Exception as exc:  # noqa: BLE001
            log.warning("错别字检查执行失败: %s", exc)
            self.collector.add_warning(f"错别字检查执行异常：{type(exc).__name__}")
            return

        protected = self._protected_spans(text)
        errors = [e for e in errors if not self._overlaps(e, protected)]

        stats_total = len(errors)
        for wrong, right, start, end in errors[:MAX_FINDINGS]:
            paragraph = text.count("\n", 0, start)
            self.collector.add(
                checker=self.checker, rule_id="typo.correction",
                severity="warning",
                message=f"疑似错别字：「{wrong}」建议改为「{right}」",
                suggestion=f"将「{wrong}」替换为「{right}」",
                location={
                    "start": start, "end": end, "paragraph_index": paragraph,
                    "snippet": text[max(0, start - 8):end + 8],
                },
            )
        if stats_total > MAX_FINDINGS:
            self.collector.add_warning(
                f"疑似错别字共 {stats_total} 处，仅展示前 {MAX_FINDINGS} 处"
            )

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
