"""L2 上下文层：对话状态机 + 槽位继承 + 省略/指代消解，纯确定性、0 token。

- 需要定位到具体 finding 的意图（explain/suggest/locate）：
  显式「第N条」> 指代「这个/这条/它」继承上文 finding > 文档仅 1 条时直接锁定；
  仍无法确定则反问（clarify），不猜。
- L1 未命中但出现指代且上文有意图：继承上文意图。
- 其余情况升级 L3。
"""

import re

from sqlalchemy.orm import Session

from app.models.chat import ChatMessage
from app.models.document import CheckFinding

_CORE_REF = re.compile(r"这个|这条|这一|该条|它")
_ORDINAL = re.compile(r"第\s*([一二三四五六七八九十百\d]+)\s*[条个]")

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

FINDING_INTENTS = {"explain_finding", "suggest_fix", "locate_finding"}
DIRECT_INTENTS = {"list_findings", "summarize"}


def _to_int(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    return _CN_NUM.get(token)


def _open_findings(db: Session, document_id) -> list[CheckFinding]:
    return (
        db.query(CheckFinding)
        .filter(CheckFinding.document_id == document_id,
                CheckFinding.status == "open")
        .order_by(CheckFinding.id)
        .all()
    )


def _last_assistant(db: Session, session_id) -> ChatMessage | None:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id,
                ChatMessage.role == "assistant")
        .order_by(ChatMessage.id.desc())
        .first()
    )


def l2_resolve(db: Session, session, text: str, intent: str | None):
    """返回结构化判定，见模块 docstring。"""
    text = (text or "").strip()
    last = _last_assistant(db, session.id)

    # L1 未命中：尝试指代继承上文意图
    if intent is None:
        if _CORE_REF.search(text) and last is not None and last.intent:
            intent = last.intent
        else:
            return {"status": "escalate"}

    slots: dict = {"inherited": bool(last is not None
                                     and intent != last.intent)}

    if intent in DIRECT_INTENTS:
        return {"status": "answer", "intent": intent, "slots": slots}

    if intent in FINDING_INTENTS:
        findings = _open_findings(db, session.document_id)
        if not findings:
            return {"status": "answer", "intent": "no_findings", "slots": slots}

        finding = None
        ordinal = _ORDINAL.search(text)
        if ordinal:
            n = _to_int(ordinal.group(1))
            if n is not None and 1 <= n <= len(findings):
                finding = findings[n - 1]
                slots["ordinal"] = n

        if finding is None and _CORE_REF.search(text):
            if last is not None and last.payload:
                fid = last.payload.get("finding_id")
                finding = next(
                    (f for f in findings if str(f.id) == str(fid)), None
                )
                slots["coref"] = True

        if finding is None and len(findings) == 1:
            finding = findings[0]
            slots["single"] = True

        if finding is None:
            return {
                "status": "clarify", "intent": intent,
                "candidates": [
                    {"finding_id": f.id, "message": f.message}
                    for f in findings[:8]
                ],
                "slots": slots,
            }

        return {
            "status": "answer", "intent": intent,
            "finding_id": finding.id, "slots": slots,
        }

    return {"status": "escalate"}
