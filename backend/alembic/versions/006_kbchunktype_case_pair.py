"""006 kbchunktype case-pair labels（仅修复 kbchunktype，避免与 005 重复）。

背景
----
005_enum_case_pair_labels 修了 4 个枚举（casesource / caseassetstatus /
scenariostatus / endpointsource），**漏了 kbchunktype**——尽管 002_knowledge_rag.py
原本设计成同时建 8 label（DEFECT/CASE/DOC/TERM/defect/case/doc/term），
但老库用户的 PG kbchunktype 枚举只含 4 个大写 label（create_all 建出来的）。

症状
----
celery-worker 跑 rebuild_knowledge_base → INSERT knowledge_chunks 时：
    asyncpg.exceptions.InvalidTextRepresentationError:
    invalid input value for enum kbchunktype: "defect"

修复
----
单独加一个 006 迁移，仅为 kbchunktype 补 4 个小写 label（防御性 ADD VALUE IF NOT EXISTS
幂等执行；大写 4 label 已存在不会重复）。
"""
from alembic import op

revision = "006"
down_revision = "005"


def upgrade() -> None:
    """为 kbchunktype 补 4 个小写 label（DEFECT/CASE/DOC/TERM 假定已存在）。"""
    # ADD VALUE IF NOT EXISTS：已存在则跳过；大写 4 label 通常已由 create_all 建好
    # DDL 无参数绑定风险：label 列表为模块内可信字面量
    for label in ("defect", "case", "doc", "term"):
        op.execute(f"ALTER TYPE kbchunktype ADD VALUE IF NOT EXISTS '{label}'")


def downgrade() -> None:
    """降级不做任何事（PG DROP TYPE 会级联删除列；生产环境绝不执行）。

    若确实需要回滚：手动 DROP TYPE kbchunktype CASCADE。
    """
    pass