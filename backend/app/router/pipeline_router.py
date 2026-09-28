"""pipeline 域路由编排：L1 → L2（pipeline 不需要 L3，缺省全部确定性可解），并落 intent_routes。"""

import logging
import time

from sqlalchemy.orm import Session

from app.models.document import IntentRoute
from app.models.user import User
from app.router import RouteResult
from app.router.l1_rule import RuleLayer
from app.router.l2_context import ContextLayer

log = logging.getLogger("router.pipeline")


def route_pipeline(
    db: Session,
    *,
    user: User,
    session_id: str,
    filename: str,
    options: dict,
    default_checks: list[str] | None = None,
) -> RouteResult:
    t0 = time.perf_counter()

    l1 = RuleLayer().match_pipeline(filename, options)
    resolved = "checks" in l1.slots and "doc_type" in l1.slots
    if resolved:
        result = l1
        result.path = "L1_HIT"
    else:
        result = ContextLayer().match_pipeline(
            l1.slots, filename, default_checks=default_checks
        )
        result.path = "L1_MISS->L2_HIT"

    result.latency_ms = int((time.perf_counter() - t0) * 1000)

    db.add(IntentRoute(
        user_id=user.id,
        session_id=session_id,
        domain="pipeline",
        final_layer=result.layer,
        path=result.path,
        intent_code=result.intent_code,
        confidence=result.confidence,
        slots=result.slots,
        latency_ms=result.latency_ms,
    ))
    return result
