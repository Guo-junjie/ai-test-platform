"""
对象存储工具 — MinIO 操作
"""

from minio import Minio
from loguru import logger
from app.config import settings

_minio_client: Minio | None = None


def init_minio():
    """初始化 MinIO 客户端，创建默认 bucket"""
    global _minio_client

    _minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )

    # 创建默认 bucket
    bucket_name = settings.MINIO_BUCKET
    try:
        if not _minio_client.bucket_exists(bucket_name):
            _minio_client.make_bucket(bucket_name)
            logger.info(f"Created MinIO bucket: {bucket_name}")
        else:
            logger.info(f"MinIO bucket exists: {bucket_name}")
    except Exception as e:
        logger.error(f"Failed to create MinIO bucket: {e}")


def get_minio_client() -> Minio:
    """获取 MinIO 客户端"""
    if _minio_client is None:
        init_minio()
    return _minio_client


def upload_file(local_path: str, object_name: str, bucket_name: str | None = None) -> str:
    """
    上传文件到 MinIO

    Returns:
        object_name (可在 MinIO 中访问的对象路径)
    """
    import os
    client = get_minio_client()
    bucket = bucket_name or settings.MINIO_BUCKET

    client.fput_object(
        bucket_name=bucket,
        object_name=object_name,
        file_path=local_path,
    )
    logger.info(f"Uploaded {local_path} to {bucket}/{object_name}")
    return object_name


def download_file(object_name: str, local_path: str, bucket_name: str | None = None) -> str:
    """
    从 MinIO 下载文件

    Returns:
        local_path
    """
    client = get_minio_client()
    bucket = bucket_name or settings.MINIO_BUCKET

    client.fget_object(
        bucket_name=bucket,
        object_name=object_name,
        file_path=local_path,
    )
    logger.info(f"Downloaded {bucket}/{object_name} to {local_path}")
    return local_path


def get_presigned_url(object_name: str, expires_hours: int = 24, bucket_name: str | None = None) -> str:
    """生成预签名 URL（用于报告分享）"""
    from datetime import timedelta
    client = get_minio_client()
    bucket = bucket_name or settings.MINIO_BUCKET

    url = client.presigned_get_object(
        bucket_name=bucket,
        object_name=object_name,
        expires=timedelta(hours=expires_hours),
    )
    return url
