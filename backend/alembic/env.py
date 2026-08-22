"""
Alembic 迁移环境配置

从 app.config 动态读取数据库 URL，从 app.models.database 导入 Base.metadata 作为 target_metadata。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings

# 导入 Base 和所有模型，确保 metadata 包含全部表定义
from app.models.database import Base
# 显式导入所有模型类，确保它们被 SQLAlchemy 注册到 Base.metadata
from app.models.database import (  # noqa: F401
    User,
    Project,
    AIModelConfig,
    ModelRouting,
    TestRun,
    TestCase,
    TestResult,
    Defect,
    TestReport,
    AuditLog,
    KnowledgeChunk,
    KnowledgeTerm,
    KBRebuildState,
)

# Alembic 配置对象
config = context.config

# 从应用配置动态设置数据库 URL（覆盖 alembic.ini 中的静态值）
config.set_main_option("sqlalchemy.url", settings.database_url)

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata — Alembic autogenerate 依赖此对象比较数据库差异
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线模式 — 生成 SQL 脚本而不连接数据库。

    适用于 CI/CD 环境中预生成迁移 SQL。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式 — 连接数据库执行迁移。

    使用连接池，迁移完成后释放连接。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
