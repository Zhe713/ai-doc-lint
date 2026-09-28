"""全局配置：所有密钥与环境差异只从环境变量 / .env 读取，不入库、不写日志。"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基础
    app_env: str = Field(default="production", alias="APP_ENV")
    secret_key: str = Field(default="dev-only-insecure-key-change-me", alias="SECRET_KEY")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")
    open_registration: bool = Field(default=True, alias="OPEN_REGISTRATION")
    login_max_failures: int = Field(default=5, alias="LOGIN_MAX_FAILURES")
    login_lock_seconds: int = Field(default=900, alias="LOGIN_LOCK_SECONDS")

    # PostgreSQL
    postgres_user: str = Field(default="aidoc", alias="POSTGRES_USER")
    postgres_password: str = Field(default="aidoc_local_pwd", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="ai_doc_lint", alias="POSTGRES_DB")
    postgres_host: str = Field(default="db", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_test_db: str = Field(default="ai_doc_lint_test", alias="POSTGRES_TEST_DB")

    # Valkey（Redis 协议）
    valkey_host: str = Field(default="cache", alias="VALKEY_HOST")
    valkey_port: int = Field(default=6379, alias="VALKEY_PORT")
    valkey_db: int = Field(default=0, alias="VALKEY_DB")
    valkey_password: str = Field(default="", alias="VALKEY_PASSWORD")

    # MinIO
    minio_endpoint: str = Field(default="storage:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="aidoc_minio", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="aidoc_minio_local_pwd", alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="documents", alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")

    # Celery / W2 解析流水线
    celery_broker_db: int = Field(default=2, alias="CELERY_BROKER_DB")
    parse_concurrency: int = Field(default=2, alias="PARSE_CONCURRENCY")
    parse_max_tasks_per_child: int = Field(default=1, alias="PARSE_MAX_TASKS_PER_CHILD")
    ocr_concurrency: int = Field(default=1, alias="OCR_CONCURRENCY")
    stalled_timeout_seconds: int = Field(default=300, alias="STALLED_TIMEOUT_SECONDS")
    max_upload_mb: int = Field(default=200, alias="MAX_UPLOAD_MB")

    # W3 意图漏斗：用户未勾选检查项时的默认集合
    default_checks: list[str] = Field(
        default_factory=lambda: ["format", "typo"], alias="DEFAULT_CHECKS"
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def test_database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_test_db}"
        )

    @property
    def valkey_url(self) -> str:
        auth = f":{self.valkey_password}@" if self.valkey_password else ""
        return f"redis://{auth}{self.valkey_host}:{self.valkey_port}/{self.valkey_db}"

    @property
    def celery_broker_url(self) -> str:
        auth = f":{self.valkey_password}@" if self.valkey_password else ""
        return f"redis://{auth}{self.valkey_host}:{self.valkey_port}/{self.celery_broker_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
