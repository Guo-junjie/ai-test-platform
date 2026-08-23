"""003_backfill_model_routing_columns - 补齐 model_routing 缺失的 6 个 model_id 列

历史背景：
    001_initial.py 仅建 5 个核心 model_id 列（code_analysis / case_generation /
    defect_analysis / fix_suggestion / fallback）。能力 1/2/4/5/6/7/9 后续陆续新增的 6 个
    插槽（doc_parse / doc_review / scenario_orchestration / script_generation /
    sql_generation / report_analysis）此前仅靠 init_db() 的 best-effort
    `ALTER TABLE model_routing ADD COLUMN IF NOT EXISTS ... VARCHAR(64)` 兜底，
    该 ALTER **不带 FK 约束**。

目标：
    将这 6 列 + 6 个 FK 全部纳入 alembic 链路，使 `alembic upgrade head` 单独运行
    即可得到完整 schema（不再依赖 init_db() 启动期兜底）。

铁律：
    - 与 init_db() 的 create_all / best-effort ALTER 幂等共存
    - 全程存在性守卫：列已存在则只补 FK；FK 已存在则跳过
    - 不破坏既有 FK（001_initial 中已建 5 个 FK；002 已加 embedding_model_id FK）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 001_initial 漏建、后续由 init_db() ALTER ADD COLUMN 兜底过的 model_id 插槽。
# 全部 nullable=True：001 创建时未给老库任何默认值，老库已有行无需 UPDATE。
_BACKFILL_COLUMNS = (
    "doc_parse_model_id",
    "doc_review_model_id",
    "scenario_orchestration_model_id",
    "script_generation_model_id",
    "sql_generation_model_id",
    "report_analysis_model_id",
)


def _fk_name_for(col_name: str) -> str:
    """生成 FK 约束名（与既有 002 命名风格保持一致：fk_model_routing_<短名>）。

    如 doc_parse_model_id → fk_model_routing_doc_parse
       scenario_orchestration_model_id → fk_model_routing_scenario_orchestration
    """
    short = col_name[: -len("_model_id")] if col_name.endswith("_model_id") else col_name
    return f"fk_model_routing_{short}"


def _is_offline() -> bool:
    """离线（--sql 生成）模式：跳过 inspect，直接无条件建/删。"""
    return op.get_context().is_offline_mode()


def upgrade() -> None:
    """补齐 6 个 model_id 列与对应 FK 约束（幂等）。"""
    if _is_offline():
        cols: set[str] = set()
        fks: set[str] = set()
    else:
        bind = op.get_bind()
        insp = inspect(bind)
        cols = {c["name"] for c in insp.get_columns("model_routing")}
        fks = {fk["name"] for fk in insp.get_foreign_keys("model_routing")}

    for col_name in _BACKFILL_COLUMNS:
        # 1) 列不存在则补（与 init_db 的 ADD COLUMN IF NOT EXISTS 互不冲突：
        #    本迁移若发现列已存在则跳过 ADD，绝不抛 "column already exists"）。
        if col_name not in cols:
            op.add_column(
                "model_routing",
                sa.Column(col_name, sa.String(64), nullable=True),
            )

        # 2) FK 不论列是否新增都要尝试建：旧库场景下 init_db 已加列却未加 FK，
        #    必须在此补建。FK 命名走 fk_model_routing_<短名>；现实 PG 自动命名
        #    是 model_routing_<col>_fkey，本迁移使用显式命名，二者不会重复。
        fk_name = _fk_name_for(col_name)
        if fk_name not in fks:
            op.create_foreign_key(
                fk_name,
                "model_routing",
                "ai_model_configs",
                [col_name],
                ["id"],
            )


def downgrade() -> None:
    """逆序：先删 FK 再删列（对称回滚，全程存在性守卫）。"""
    cols: set[str]
    fks: set[str]
    if _is_offline():
        cols = set()
        fks = set()
    else:
        bind = op.get_bind()
        insp = inspect(bind)
        cols = {c["name"] for c in insp.get_columns("model_routing")}
        fks = {fk["name"] for fk in insp.get_foreign_keys("model_routing")}

    for col_name in reversed(_BACKFILL_COLUMNS):
        fk_name = _fk_name_for(col_name)
        if fk_name in fks:
            op.drop_constraint(fk_name, "model_routing", type_="foreignkey")
        if col_name in cols:
            op.drop_column("model_routing", col_name)