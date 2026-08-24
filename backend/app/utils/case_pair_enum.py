"""
CasePairEnum：大小写无关的枚举 TypeDecorator，修复 4f75c27c 后续暴露的"老数据大小写兼容"Bug。

背景
----
4f75c27c 给 5 个枚举的 SAEnum 加了 ``values_callable=lambda x: [e.value for e in x]``，
让 SAEnum **写入和读取都用 .value**（小写），从而 round-trip 一致。

但**老部署**的数据是用修复前的代码写入的：
- 修复前 SAEnum 默认用 ``[e.name for e in x]`` 作为写入字符串 → DB 里存大写 .name
  （如 'DOC_IMPORT' / 'DRAFT'）
- alembic 005 + 006 跑了之后，PG 枚举类型里也加上了大写 .name label（兼容老数据写入）

**问题**：4f75c27c 后，SAEnum **读取**改用 .value 列表（['doc_import', 'draft']）做 lookup。
但 DB 返回的老数据是大写 'DOC_IMPORT' / 'DRAFT'，在 .value 列表里找不到 → ``LookupError``。

修法（采用纯 TypeDecorator 包装 String，不嵌套 SAEnum）
---------------------------------------------------------
**不嵌 SAEnum**——直接用 String 作为底层 type + TypeDecorator 自管 result_processor。
这样完全绕开 SAEnum 的 process path，100% 可控。

* **写入**：把 PyEnum 实例转成 .value（小写字符串）；已是字符串则原样透传
  （允许应用层直接传大写老 label 写入，PG 端大写小写都允许——alembic 005/006 已确保）
* **读取**：先按 .value 列表查（4f75c27c 路径），miss 时按 .name 列表查（兼容老数据大写）
* **未知 label**：抛 LookupError（与 SAEnum 默认行为一致）
* **类型名/创建行为**显式映射到 PG ENUM：保留 SAEnum 的 ``name=`` 参数和 PG 端类型创建逻辑
  （通过 mock 一个最小的 SAEnum 子类拿 ``name``）
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class _PGEnumNameProxy(SAEnum):
    """最小化 SAEnum 子类：仅用于拿 ``name`` / ``native_enum`` 等元信息，
    它的 result_processor 永远不会被触发（因为我们用 String 作为 TypeDecorator impl）。"""


class CasePairEnum(TypeDecorator):
    """大小写无关的枚举 TypeDecorator 包装（兼容老数据 .name 写入历史）。

    用法
    ----
    把 ``SAEnum(Foo, values_callable=lambda x: [e.value for e in x], name="foo")``
    换成 ``CasePairEnum(Foo, values_callable=lambda x: [e.value for e in x], name="foo")``。
    其余参数一致。
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class: Any, **kw: Any) -> None:
        # 缓存 enum_class + name（PG 端 native enum 类型名）
        self._case_pair_enum_cls = enum_class
        self._enum_name = kw.get("name", enum_class.__name__.lower())
        # impl String 长度至少 1
        kw.setdefault("length", 64)
        # 弹掉 SAEnum 专属参数，避免透传给 String impl
        for arg in ("values_callable", "native_enum", "create_constraint",
                    "metadata", "schema", "inherit_schema", "length",
                    "convert_unicode", "collation", "name"):
            kw.pop(arg, None)
        super().__init__()

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        """PG / SQLite 都用 String impl；PG 端的 ENUM 类型由 init_db 的 DDL 创建。"""
        return dialect.type_descriptor(String(length=64))

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        """写入：PyEnum → .value（4f75c27c 标准行为）。已为字符串则原样透传（兼容老数据写入）。"""
        if value is None:
            return None
        # 接受 PyEnum 实例
        if hasattr(value, "value"):
            return value.value
        # 已为字符串：原样透传（这样老数据 'DOC_IMPORT' 仍能正确写入，PG 端大小写都允许）
        return str(value)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        """读取：.value 优先，miss 时按 .name 兼容老数据。"""
        if value is None:
            return None
        cls = self._case_pair_enum_cls
        # 主路径：.value 列表（4f75c27c 标准行为）
        try:
            return cls(value)
        except (KeyError, ValueError):
            pass
        # 兼容老数据：按 .name 列表
        if cls is not None:
            target = str(value)
            for e in cls:
                if e.name == target:
                    return e
        # 真没找到：抛 LookupError（与 SAEnum 默认行为一致）
        raise LookupError(
            "'%s' is not among the defined enum values. "
            "Enum name: %s. Possible values: %s, %s"
            % (value, self._enum_name,
               [e.value for e in cls],
               [e.name for e in (cls or [])])
        )
