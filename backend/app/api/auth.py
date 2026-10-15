"""认证接口：注册 / 登录 / 刷新 / 登出。"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from app.services import auth_service, setup_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "-"


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> User:
    if not setup_service.is_registration_open(db):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="管理员已关闭开放注册")
    try:
        user = auth_service.register(db, body.username, body.password)
    except auth_service.AuthError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    # W8 审计：注册留痕
    from app.services.audit_service import write_audit

    write_audit(db, action="register", username=user.username, ip=_client_ip(request))
    db.commit()
    return auth_service.user_public(user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    ip = _client_ip(request)
    try:
        tokens = auth_service.login(
            db,
            body.username,
            body.password,
            request.headers.get("user-agent"),
            ip,
        )
    except auth_service.AuthError as exc:
        from fastapi import HTTPException

        # W8 审计：登录失败留痕（不记密码）
        from app.services.audit_service import write_audit

        write_audit(
            db, action="login_fail", username=body.username,
            detail={"reason": exc.message}, ip=ip,
        )
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    # W8 审计：登录成功留痕
    from sqlalchemy import select

    from app.services.audit_service import write_audit

    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    write_audit(db, action="login_success", user_id=user.id if user else None,
                username=body.username, ip=ip)
    db.commit()
    return TokenOut(**tokens)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenOut:
    try:
        tokens = auth_service.refresh_tokens(db, body.refresh_token)
    except auth_service.AuthError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return TokenOut(**tokens)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Response:
    # refresh token 放在请求体或 x-refresh-token 头中
    refresh_token = request.headers.get("x-refresh-token")
    auth_service.logout(db, refresh_token)
    response.status_code = 204
    return response
