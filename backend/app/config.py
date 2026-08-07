"""
AI 自动化测试平台 — 全局配置
"""

import os
from functools import lru_cache
from pydantic import BaseModel


class Settings(BaseModel):
    """应用全局配置"""

    # 应用环境
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_DEBUG: bool = os.getenv("APP_DEBUG", "true").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    AES_ENCRYPTION_KEY: str = os.getenv("AES_ENCRYPTION_KEY", "0" * 32)

    # 数据库
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "aitp")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "aitp_secret_2026")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "ai_test_platform")

    # Redis
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")

    # RabbitMQ
    RABBITMQ_HOST: str = os.getenv("RABBITMQ_HOST", "localhost")
    RABBITMQ_PORT: int = int(os.getenv("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER: str = os.getenv("RABBITMQ_USER", "aitp")
    RABBITMQ_PASSWORD: str = os.getenv("RABBITMQ_PASSWORD", "aitp_secret_2026")

    # MinIO
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "aitp")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "aitp_secret_2026")
    MINIO_BUCKET: str = os.getenv("MINIO_BUCKET", "ai-test-platform")
    MINIO_SECURE: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"

    # GitHub
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_WEBHOOK_SECRET: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")

    # AI 模型默认配置
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    OPENAI_MODEL_NAME: str = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_API_BASE: str = os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com")
    ANTHROPIC_MODEL_NAME: str = os.getenv("ANTHROPIC_MODEL_NAME", "claude-sonnet-4-20250514")
    CUSTOM_MODEL_API_BASE: str = os.getenv("CUSTOM_MODEL_API_BASE", "")
    CUSTOM_MODEL_API_KEY: str = os.getenv("CUSTOM_MODEL_API_KEY", "")
    CUSTOM_MODEL_NAME: str = os.getenv("CUSTOM_MODEL_NAME", "")

    # 文件路径
    WORKSPACE_DIR: str = os.getenv("WORKSPACE_DIR", "/app/data/repos")
    REPORT_DIR: str = os.getenv("REPORT_DIR", "/app/data/reports")

    # SVN
    SVN_DEFAULT_TIMEOUT: int = int(os.getenv("SVN_DEFAULT_TIMEOUT", "120"))

    @property
    def database_url(self) -> str:
        """同步数据库连接 URL（用于 Alembic 迁移等）"""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def async_database_url(self) -> str:
        """异步数据库连接 URL（用于 SQLAlchemy async）"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        """Redis 连接 URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    @property
    def celery_broker_url(self) -> str:
        """Celery broker URL (RabbitMQ)"""
        return (
            f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}"
            f"@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}//"
        )

    @property
    def celery_result_backend(self) -> str:
        """Celery result backend (Redis)"""
        return self.redis_url


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
