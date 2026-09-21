"""首次启动初始化接口。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import SetupAdminIn, SetupStatusOut
from app.services import auth_service, setup_service

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatusOut)
def setup_status(db: Session = Depends(get_db)) -> SetupStatusOut:
    return SetupStatusOut(
        needs_setup=setup_service.needs_setup(db),
        open_registration=setup_service.is_registration_open(db),
    )


@router.post("/admin", status_code=201)
def create_admin(body: SetupAdminIn, db: Session = Depends(get_db)) -> dict:
    if not setup_service.needs_setup(db):
        raise HTTPException(status_code=409, detail="系统已初始化，初始化接口仅可使用一次")
    try:
        admin = setup_service.create_initial_admin(db, body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"id": str(admin.id), "username": admin.username, "roles": admin.role_names}
