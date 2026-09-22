"""MinIO（S3 兼容）客户端与对象读写工具。"""

from io import BytesIO

from minio import Minio

from app.core.config import settings

minio_client = Minio(
    settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_secure,
)


def ensure_bucket() -> bool:
    """启动时确保默认存储桶存在；返回存储是否可用。"""
    if not minio_client.bucket_exists(settings.minio_bucket):
        minio_client.make_bucket(settings.minio_bucket)
    return True


def put_object(key: str, data: bytes, content_type: str | None = None) -> str:
    minio_client.put_object(
        settings.minio_bucket, key, BytesIO(data), length=len(data), content_type=content_type or "application/octet-stream"
    )
    return key


def get_object_bytes(key: str) -> bytes:
    resp = None
    try:
        resp = minio_client.get_object(settings.minio_bucket, key)
        return resp.read()
    finally:
        if resp is not None:
            resp.close()
            resp.release_conn()


def remove_object(key: str) -> None:
    minio_client.remove_object(settings.minio_bucket, key)
