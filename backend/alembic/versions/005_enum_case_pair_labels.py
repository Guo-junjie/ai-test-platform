"""005 enum case-pair labels: casesource / caseassetstatus / scenariostatus / endpointsource

本迁移解决 SAEnum 持久化大小写与 PG 枚举标签不匹配的问题：

症状
----
SAEnum(PyEnum) 在不同 SQLAlchemy 版本下，会用 PyEnum 成员 NAME（大写）或
VALUE（小写）作为 PG 枚举写入值。当 SAEnum 写入的是小写（AI_GENERATED -> "ai_generated"）
而 PG 枚举只有大写标签（"AI_GENERATED"）时，asyncpg 会抛：
    asyncpg.exceptions.InvalidTextRepresentationError:
    invalid input value for enum casesource: "ai_generated"

修复
----
为 4 个枚举类型同时存在大写 NAME 与小写 VALUE 两套标签，兼容任一写入方式。
幂等：ADD VALUE IF NOT EXISTS，重复执行不报错。

注意
----
- PostgreSQL ALTER TYPE ... ADD VALUE 必须 AUTOCOMMIT 事务外执行，
  这里保留与 002_kb_rag / 003_backfill_model_routing 一致的风格。
- 使用 downgrade() 时 DROP TYPE 会连带删除引用此类型的所有列（DROP CASCADE），
  生产环境不要执行；本方法仅为 alembic revision 一致性存在。
"""
from alembic import op

revision = "005"
down_revision = "004"


# 枚举类型 -> 包含的 label 列表（成员名 + 成员值 各一份，兼容双向写入）
ENUM_LABEL_PAIRS: list[tuple[str, list[str]]] = [
    # casesource: AI_GENERATED/ai_generated, MANUAL/manual
    ("casesource", ["AI_GENERATED", "ai_generated", "MANUAL", "manual"]),
    # caseassetstatus: DRAFT/draft, ADOPTED/adopted, DEPRECATED/deprecated
    (
        "caseassetstatus",
        ["DRAFT", "draft", "ADOPTED", "adopted", "DEPRECATED", "deprecated"],
    ),
    # scenariostatus: DRAFT/draft, ORCHESTRATED/orchestrated, ADOPTED/adopted
    (
        "scenariostatus",
        ["DRAFT", "draft", "ORCHESTRATED", "orchestrated", "ADOPTED", "adopted"],
    ),
    # endpointsource: DOC_IMPORT/doc_import, MANUAL/manual, AI_PARSE/ai_parse, OPENAPI_IMPORT/openapi_import
    (
        "endpointsource",
        [
            "DOC_IMPORT",
            "doc_import",
            "MANUAL",
            "manual",
            "AI_PARSE",
            "ai_parse",
            "OPENAPI_IMPORT",
            "openapi_import",
        ],
    ),
]


def upgrade() -> None:
    """为 4 个枚举类型同时添加大写 + 小写 label（兼容 SAEnum 大小写双向写入）。"""
    for type_name, labels in ENUM_LABEL_PAIRS:
        for label in labels:
            # ADD VALUE IF NOT EXISTS：标签已存在则跳过
            # DDL 无参数绑定风险：type_name/labels 均为模块内可信字面量
            op.execute(
                f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'"
            )


def downgrade() -> None:
    """降级不做任何事（PG DROP TYPE 会连带删除列；生产环境绝不执行）。

    若确实需要回滚：手动 DROP TYPE {type_name} CASCADE 后再 DROP COLUMN。
    """
    # 故意留空 — PostgreSQL 移除枚举 label 需重新建类型（复杂），且 DROP TYPE
    # 会级联删除所有引用此类型的列。回滚策略见 docstring。
    pass