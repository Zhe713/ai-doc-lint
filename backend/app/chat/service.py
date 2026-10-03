"""对话编排：L1 → L2 → L3，确定性回答生成与分流口径。"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.chat.l1_rule import l1_match
from app.chat.l2_context import l2_resolve
from app.models.chat import ChatMessage
from app.models.document import CheckFinding

SEV_LABEL = {"error": "错误", "warning": "警告", "info": "提示"}


@dataclass
class DirectTurn:
    answer: str
    route_layer: str
    intent: str
    payload: dict = field(default_factory=dict)


@dataclass
class L3Turn:
    document_id: str
    history: list
    user_text: str


def _finding_line(idx: int, f: CheckFinding) -> str:
    return f"{idx}.【{SEV_LABEL.get(f.severity, '提示')}】{f.message}"


def _list_answer(db: Session, document_id) -> str:
    rows = (
        db.query(CheckFinding)
        .filter(CheckFinding.document_id == document_id,
                CheckFinding.status == "open")
        .order_by(CheckFinding.id)
        .all()
    )
    if not rows:
        return "当前文档没有待处理问题。"
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in rows:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    head = (
        f"共 {len(rows)} 个待处理问题"
        f"（错误 {counts['error']}、警告 {counts['warning']}、"
        f"提示 {counts['info']}）："
    )
    return "\n".join([head] + [_finding_line(i, f)
                               for i, f in enumerate(rows, 1)])


def _summary_answer(db: Session, document_id) -> str:
    rows = (
        db.query(CheckFinding)
        .filter(CheckFinding.document_id == document_id)
        .order_by(CheckFinding.id)
        .all()
    )
    if not rows:
        return "该文档未发现问题，整体校验通过。"
    open_rows = [f for f in rows if f.status == "open"]
    if not open_rows:
        return f"共发现 {len(rows)} 个问题，均已处理完毕。"
    top = [f for f in open_rows if f.severity == "error"]
    tail = ""
    if top:
        tail = "建议优先处理错误项：" + "；".join(
            f.message for f in top[:3]
        )
    return (
        f"共发现 {len(rows)} 个问题，当前待处理 {len(open_rows)} 个。" + tail
    )


def _finding_answer(intent: str, f: CheckFinding) -> str:
    label = SEV_LABEL.get(f.severity, "提示")
    if intent == "explain_finding":
        text = f"这是一条【{label}】级问题：{f.message}。"
        if f.suggestion:
            text += f" 处理方向：{f.suggestion}。"
        return text
    if intent == "suggest_fix":
        if f.suggestion:
            return f"修改建议：{f.suggestion}。"
        return "该问题暂无自动修改建议，请结合业务咨询专业人员。"
    # locate_finding
    snippet = (f.location or {}).get("snippet")
    if snippet:
        return f"对应原文位置：…{snippet}…"
    return "未能自动定位到原文位置，请对照报告中的相关段落。"


def _clarify_answer(verdict: dict) -> str:
    lines = ["你指的是哪一条？"]
    for i, cand in enumerate(verdict["candidates"], 1):
        lines.append(f"{i}. {cand['message']}")
    return "\n".join(lines)


def _history(db: Session, session) -> list[dict]:
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
        .all()
    )
    return [{"role": m.role, "content": m.content}
            for m in rows if m.content][-8:]


def handle_turn(db: Session, session, user_text: str,
                button_intent: str | None = None):
    intent, _conf = l1_match(user_text, button_intent=button_intent)
    verdict = l2_resolve(db, session, user_text, intent)
    status = verdict["status"]

    if status == "escalate":
        return L3Turn(
            document_id=str(session.document_id),
            history=_history(db, session), user_text=user_text,
        )

    if status == "clarify":
        return DirectTurn(
            answer=_clarify_answer(verdict),
            route_layer="l2_context",
            intent=verdict["intent"],
            payload={"clarify": True, "slots": verdict.get("slots")},
        )

    resolved_intent = verdict["intent"]
    slots = verdict.get("slots", {})

    if resolved_intent == "list_findings":
        answer = _list_answer(db, session.document_id)
    elif resolved_intent == "summarize":
        answer = _summary_answer(db, session.document_id)
    elif resolved_intent == "no_findings":
        answer = "当前文档没有待处理问题。"
    else:
        finding = db.get(CheckFinding, verdict["finding_id"])
        answer = _finding_answer(resolved_intent, finding)

    # 用上文继承/指代才计入 L2；同句可判定的计入 L1
    used_context = bool(slots.get("coref") or slots.get("inherited"))
    route_layer = "l2_context" if used_context else "l1_rule"
    payload = {"slots": slots}
    if "finding_id" in verdict:
        payload["finding_id"] = str(verdict["finding_id"])

    return DirectTurn(
        answer=answer, route_layer=route_layer,
        intent=resolved_intent, payload=payload,
    )
