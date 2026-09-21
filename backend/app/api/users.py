"""当前用户接口。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import UserOut
from app.services import auth_service

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=UserOut)
def read_me(current: User = Depends(get_current_user)) -> dict:
    return auth_service.user_public(current)
