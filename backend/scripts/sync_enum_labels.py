"""一键修复 PG 枚举的双 label 同步脚本（运维手动调用）。

用途
----
``init_db()`` 在 backend 启动期会跑一次 ``sync_enum_case_pairs`` 兜底补齐 label，
但**用户不重启 backend** 的场景下报错会一直存在：

* ``invalid input value for enum casesource: "requirement"``（commit 182fb2b 加的新值）
* ``column "x" is of type scenariostatus but expression is of type character varying``
* ...

本脚本在 ``app/utils/enum_sync.run_enum_sync_and_report()`` 之上做最简包装，
**不依赖 backend 进程** —— 直接连 DB（用 ``backend/.env`` 的 ``DATABASE_URL``）即可。

用法
----
1. **部署机**（默认连容器内 PG）：
   ::

       docker compose exec backend python -m scripts.sync_enum_labels

2. **本机** 端口映射到 localhost:5432 时（开发常见）：
   ::

       DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/db \\
           python -m scripts.sync_enum_labels

退出码
------
* ``0`` —— 全部 label 已存在或同步成功
* ``1`` —— 有 label 补失败（如正在被使用，重启 backend 后由 init_db 兜底）
"""
from __future__ import annotations

import asyncio
import os
import sys

# 让 ``python -m scripts.sync_enum_labels`` 与 ``docker compose exec backend ...`` 都能 import app
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_BACKEND_DIR)
for p in (_PARENT, _BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


async def main() -> int:
    from app.utils.enum_sync import run_enum_sync_and_report  # noqa: E402
    from app.utils.database import async_engine  # noqa: E402

    report = await run_enum_sync_and_report(async_engine)

    # 检查是否有任何失败（label 带 ❌ 前缀）
    all_added: list[str] = []
    for info in report.values():
        all_added.extend(info["added"])
    failed = [a for a in all_added if a.startswith("❌")]

    await async_engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
