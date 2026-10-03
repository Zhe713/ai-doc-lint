"""对话助手接口（W4 Day19）：会话管理 + SSE 流式消息。"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.chat import l3_agent
from app.chat.service import DirectTurn, L3Turn, handle_turn
from app.core.deps import get_current_user
from app.db.session import SessionLocal, get_db
from app.llm.client import LLMCallError, LLMNotConfiguredError
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document, IntentRoute
from app.models.llm import LLMCallLog
from app.models.user import User

router = APIRouter(prefix="/chat", tags=["chat"])

_LAYER = {"l1_rule": "rule", "l2_context": "context", "l3_agent": "llm"}


def _sse(event: dict) -> bytes:
    return (
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
    )


def _write_route(db, user_id, session, route_layer, intent, *,
                 slots=None, tool_calls=None, tokens=None, model=None):
    db.add(IntentRoute(
        user_id=user_id, session_id=str(session.id), domain="chat",
        final_layer=_LAYER[route_layer], intent_code=intent,
        slots=slots, tool_calls=tool_calls, tokens=tokens, model=model,
    ))


# ---------------- schemas ----------------


class SessionCreate(BaseModel):
    document_id: uuid.UUID
    title: str | None = None


class MessageCreate(BaseModel):
    content: str
    button_intent: str | None = None


# ---------------- 会话管理 ----------------


@router.post("/sessions", status_code=201)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    doc = db.get(Document, body.document_id)
    if doc is None or doc.user_id != current.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    session = ChatSession(
        user_id=current.id, document_id=doc.id,
        title=body.title or f"{doc.filename} 对话",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "title": session.title}


@router.get("/sessions")
def list_sessions(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current.id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return [{"id": s.id, "title": s.title,
             "document_id": s.document_id} for s in rows]


@router.get("/sessions/{session_id}")
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    s = db.get(ChatSession, session_id)
    if s is None or s.user_id != current.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "id": s.id, "title": s.title, "document_id": s.document_id,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content,
             "route_layer": m.route_layer, "intent": m.intent}
            for m in s.messages
        ],
    }


# ---------------- 流式消息 ----------------


@router.post("/sessions/{session_id}/messages")
def post_message(
    session_id: uuid.UUID,
    body: MessageCreate,
    current: User = Depends(get_current_user),
):
    async def event_gen():
        db = SessionLocal()
        try:
            session = db.get(ChatSession, session_id)
            if session is None or session.user_id != current.id:
                yield _sse({"type": "error", "text": "会话不存在"})
                return

            db.add(ChatMessage(
                session_id=session.id, role="user", content=body.content,
            ))
            db.commit()

            result = handle_turn(
                db, session, body.content,
                button_intent=body.button_intent,
            )

            if isinstance(result, DirectTurn):
                assistant = ChatMessage(
                    session_id=session.id, role="assistant",
                    content=result.answer, route_layer=result.route_layer,
                    intent=result.intent, payload=result.payload,
                )
                db.add(assistant)
                _write_route(
                    db, current.id, session, result.route_layer,
                    result.intent, slots=result.payload.get("slots"),
                )
                db.commit()
                yield _sse({"type": "delta", "text": result.answer})
                yield _sse({"type": "done", "message_id": assistant.id})
                return

            # L3：function calling + 流式回答
            assert isinstance(result, L3Turn)
            parts: list[str] = []
            meta = {}
            for kind, data in l3_agent.run_l3(
                db, session.document_id, result.history, result.user_text
            ):
                if kind == "delta":
                    parts.append(data)
                    yield _sse({"type": "delta", "text": data})
                else:
                    meta = data

            answer = "".join(parts)
            assistant = ChatMessage(
                session_id=session.id, role="assistant",
                content=answer, route_layer="l3_agent",
                intent="agent", payload={"tool_calls": meta.get("tool_calls")},
            )
            db.add(assistant)
            tokens = (meta.get("prompt_tokens", 0)
                      + meta.get("completion_tokens", 0))
            _write_route(
                db, current.id, session, "l3_agent", "agent",
                tool_calls=meta.get("tool_calls"), tokens=tokens,
                model=meta.get("model"),
            )
            db.add(LLMCallLog(
                user_id=current.id, scene="chat", provider="primary",
                model=meta.get("model", ""),
                prompt_tokens=meta.get("prompt_tokens", 0),
                completion_tokens=meta.get("completion_tokens", 0),
                total_tokens=tokens, success=True,
            ))
            db.commit()
            yield _sse({"type": "done", "message_id": assistant.id})
        except (LLMNotConfiguredError, LLMCallError) as exc:
            yield _sse({
                "type": "error",
                "text": f"大模型不可用（{type(exc).__name__}），"
                        "可先使用快捷问题或检查 LLM 配置",
            })
        except Exception:  # noqa: BLE001
            yield _sse({"type": "error", "text": "处理失败，请重试"})
        finally:
            db.close()

    return StreamingResponse(
        event_gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
