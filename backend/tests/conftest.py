"""pytest 夹具：在独立测试库上建表，覆盖 get_db 依赖；Valkey 使用独立 db 并清空。"""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 限流/缓存走独立 Valkey db，避免污染开发数据
os.environ.setdefault("VALKEY_DB", "1")

from app.core.config import settings  # noqa: E402

settings.valkey_db = 1

from app.core.ratelimit import get_redis  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import *  # noqa: E402,F401,F403  确保 metadata 收集完整


def _ensure_test_database() -> None:
    admin_dsn = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/postgres"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_test_db,)
        ).fetchone()
        if not exists:
            conn.execute(f"CREATE DATABASE {settings.postgres_test_db}")


_ensure_test_database()

test_engine = create_engine(settings.test_database_url, future=True)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, future=True)

Base.metadata.drop_all(bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def _override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="session", autouse=True)
def _clean_redis():
    client = get_redis()
    client.flushdb()
    # 角色种子（测试库不走迁移）
    from app.services.setup_service import ensure_roles

    with TestSessionLocal() as db:
        ensure_roles(db)
    yield
    client.flushdb()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def pristine(client):
    """全新库状态：重建全部表、仅保留角色种子、清空限流，用于首次初始化类用例。"""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    from app.services.setup_service import ensure_roles

    with TestSessionLocal() as db:
        ensure_roles(db)
    get_redis().flushdb()
    return client
