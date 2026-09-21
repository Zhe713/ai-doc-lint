"""MinIO（S3 兼容）客户端与启动建桶。"""

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
