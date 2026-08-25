"""
CasePairEnum：大小写无关的 SAEnum TypeDecorator 包装，修复 4f75c27c 后续暴露的两个 Bug。

修复两个 Bug
------------
**Bug A：老数据大小写兼容**
4f75c27c 给 5 个枚举的 SAEnum 加了 ``values_callable=lambda x: [e.value for e in x]``，
让 SAEnum **写入和读取都用 .value**（小写），从而 round-trip 一致。

但**老部署**的数据是用修复前的代码写入的（大写 .name），
4f75c27c 后的 SAEnum **读取**用 .value 列表查老数据会 ``LookupError``。

**Bug B：用 String 底层导致 enum 列写入报 DatatypeMismatchError**（用户 16:21 报错）
- 早期用 `TypeDecorator(String, ...)` 绕开 SAEnum 1.4 缓存问题
- 但 String 底层让 SAEnum 失去 enum 上下文，bind 阶段生成 `$1::VARCHAR` cast
- PG 端列是 enum → 报 ``column "status" is of type caseassetstatus but expression is of type character varying``

最终方案
--------
**TypeDecorator + impl = SAEnum**（不是 String）：

* **底层 impl = SAEnum**：SQLAlchemy 在 PG 下用 ENUM（asyncpg 走 enum adapter，bind 阶段生成
  ``$1::caseassetstatus`` cast 而不是 ``$1::VARCHAR``）→ **修 Bug B**
* **process_bind_param 完全自管**：接受 PyEnum 实例或字符串（兼容老 .name 大写），
  输出 .value 小写字符串（与 4f75c27c 一致）
* **process_result_value 完全自管**：主路径 cls(value)（.value 列表），fallback 遍历 .name
  （兼容老数据大写）→ **修 Bug A**
* **未知 label**：抛 LookupError（不静默吞错）
* TypeDecorator 比 SAEnum 子类更可控：不需要依赖 SQLAlchemy 不同版本下的私有方法
  override 行为
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy.types import TypeDecorator


# SAEnum 专属参数（不传给 String 父类）
_SAENUM_KEYS = frozenset({
    "values_callable", "name", "native_enum", "create_constraint",
    "metadata", "schema", "inherit_schema",
})


class CasePairEnum(TypeDecorator):
    """大小写无关的 SAEnum 包装：写用 .value、读兼容老 .name、不丢 enum 列 cast。

    用法
    ----
    把 ``SAEnum(Foo, values_callable=lambda x: [e.value for e in x], name="foo")``
    换成 ``CasePairEnum(Foo, values_callable=lambda x: [e.value for e in x], name="foo")``。
    其余参数一致。
    """

    impl = SAEnum
    cache_ok = True

    def __init__(self, enum_class: Any, **kw: Any) -> None:
        # 缓存 enum_class 供 fallback 路径使用
        self._case_pair_enum_cls = enum_class
        # 拆 SAEnum 专属参数 vs 透传给 SAEnum 实例构造
        saenum_kw = {k: kw.pop(k) for k in list(kw) if k in _SAENUM_KEYS}
        # 显式构造底层 SAEnum 实例（PG 端用 ENUM impl，asyncpg 走 enum adapter）
        # **不要**传 `length` 给 SAEnum —— SQLAlchemy 2.0 一旦看到 length 就会走 VARCHAR 路径，
        # 但 asyncpg dialect 又会因为 impl=SAEnum 看到 enum 列上下文 → 抛
        # "CompileError: PostgreSQL AsyncPgEnum type requires a name"。
        # 旧 commit 8cd535e6 误加 `setdefault("length", 64)` 是这个隐形 bug 的源头
        # ——老库没事是因为表已建过 create_all checkfirst 跳过；新部署 / down -v 后
        # init_db() 会炸，让 _run_lifecycle_step 吞掉 + 整个 schema 缺失。
        self._saenum_impl = SAEnum(enum_class, **saenum_kw)
        # 父类 TypeDecorator 不需要再传 enum_class / values_callable
        super().__init__()

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        """关键：让 SAEnum 在 dialect 适配时拿到我们的 enum_class。"""
        return self._saenum_impl

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        """写入：PyEnum → .value（4f75c27c 行为），字符串兼容 .name → .value 转换。

        接受三种输入：
        1. PyEnum 实例（CaseAssetStatus.DRAFT）→ .value "draft"
        2. 已经是 .value 字符串（"draft"）→ 原样返回
        3. 老代码大写 .name 字符串（"ADOPTED"）→ 找 .name 匹配 → 返回 .value "adopted"

        asyncpg 拿到字符串后用 enum adapter cast 到 ``::caseassetstatus`` 列。
        """
        if value is None:
            return None
        cls = self._case_pair_enum_cls
        # 1) PyEnum 实例
        if hasattr(value, "value") and hasattr(value, "name"):
            return value.value
        # 2) 字符串：尝试 .value（小写）→ fallback .name
        if isinstance(value, str):
            try:
                return cls(value).value  # 是 .value 形式
            except (KeyError, ValueError):
                pass
            # 兼容大写 .name（用户 API 代码常这样写 `item.status = "ADOPTED"`）
            for e in cls:
                if e.name == value:
                    return e.value
        # 3) 都不是 → 抛 LookupError
        raise LookupError(
            f"Invalid value for enum {cls.__name__}: {value!r}. "
            f"Valid: {[e.value for e in cls]} or {[e.name for e in cls]}"
        )

    def result_processor(self, dialect, coltype):  # type: ignore[override]
        """完全自管 result_processor：主路径 .value，miss 时按 .name 兼容老数据。

        **不**用 TypeDecorator 默认实现（默认会调底层 SAEnum 的 impl_processor，SAEnum
        默认 .value 查不到大写会直接抛 LookupError，绕开了我们的 fallback）。
        """
        cls = self._case_pair_enum_cls

        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                # 主路径：.value 列表（4f75c27c 标准行为）
                try:
                    return cls(value)
                except (KeyError, ValueError):
                    pass
                # 兼容老数据：按 .name 列表
                for e in cls:
                    if e.name == value:
                        return e
            # 已经是枚举实例 / 未知类型
            raise LookupError(
                f"'{value}' is not among the defined enum values. "
                f"Enum name: {cls.__name__}. "
                f"Possible values: {[e.value for e in cls]}, {[e.name for e in cls]}"
            )

        return process
