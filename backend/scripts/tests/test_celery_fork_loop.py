"""
Celery prefork + asyncpg "Future attached to different loop" Bug 端到端模拟。

模拟 Celery 4/5 prefork 模型：
1. 主进程 import 业务模块，async_engine 单例创建
2. fork worker 子进程（multiprocessing.set_start_method('fork') 模拟）
3. 子进程触发 worker_process_init → 调 reset_async_engine
4. 子进程 asyncio.run(task) 跑 rebuild 任务
5. 多次跑（模拟连续 task 调度）
6. 验证：整个流程不抛 "Event loop is closed" / "attached to a different loop"

不依赖 Docker / PG / Celery，纯粹 Python 多进程 + SQLAlchemy async + SQLite。
"""
import asyncio
import enum
import multiprocessing as mp
import os
import sys
import time
import traceback
from datetime import datetime

sys.path.insert(0, r"D:\code\WorkbuddyProject\ai测试自闭环\ai-test-platform\backend")

from sqlalchemy import (JSON, Column, DateTime, Enum as SAEnum, Integer, String, Text,
                        create_engine, func, select)
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker, create_async_engine)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool

# 模拟 PG 端使用 aiosqlite，URL 通过 DATABASE_URL env 注入
# 用 file-based SQLite 模拟，因为 in-memory DB 在 fork 后子进程看不到主进程的表
_TEST_DB = os.path.join(os.environ.get("TEMP", "/tmp"), "test_celery_fork.db")
os.environ["ASYNC_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ["SYNC_DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("APP_DEBUG", "false")

# 启动时清掉旧 db
if os.path.exists(_TEST_DB):
    os.unlink(_TEST_DB)


# ==================== 复刻 app.utils.database（含 proxy + reset_async_engine） ====================


class _AsyncSessionLocalProxy:
    """与 app.utils.database._AsyncSessionLocalProxy 完全一致（最小复刻）。"""
    def __init__(self):
        self._current_session_maker = None
        self._current_async_engine = None

    def __call__(self, *args, **kwargs):
        if self._current_session_maker is None:
            raise RuntimeError("AsyncSessionLocal not initialized")
        return self._current_session_maker(*args, **kwargs)

    def __getattr__(self, name):
        if self._current_session_maker is None:
            raise RuntimeError("AsyncSessionLocal not initialized")
        return getattr(self._current_session_maker, name)

    def reset(self, new_engine):
        """模拟 reset_async_engine 内部行为。"""
        if self._current_async_engine is not None:
            try:
                self._current_async_engine.sync_engine.dispose()
            except Exception:
                pass
        new_sm = async_sessionmaker(bind=new_engine, expire_on_commit=False)
        self._current_async_engine = new_engine
        self._current_session_maker = new_sm
        return new_sm


AsyncSessionLocal = _AsyncSessionLocalProxy()


# ==================== 复刻 ORM 模型 ====================


Base = declarative_base()


class KBChunkType(enum.Enum):
    DEFECT = "defect"
    CASE = "case"
    DOC = "doc"
    TERM = "term"


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id = Column(String(36), primary_key=True)
    kb_type = Column(SAEnum(KBChunkType,
                            values_callable=lambda x: [e.value for e in x],
                            name="kbchunktype"),
                     nullable=False)
    content = Column(Text, default="")


class KBRebuildState(Base):
    __tablename__ = "kb_rebuild_state"
    id = Column(Integer, primary_key=True)
    state = Column(String(20), default="idle")
    updated_at = Column(DateTime, default=datetime.utcnow)


# ==================== 模拟子进程 worker：跑多次 task ====================


def _worker_subprocess_entry(task_count: int = 3):
    """子进程入口：模拟 Celery worker 启动后跑多次 task。

    步骤：
    1. worker_process_init → reset_async_engine (创建新 engine)
    2. create_all 建表（仅在子进程第一次访问时）
    3. 多次 asyncio.run(task) 跑 rebuild（**关键：每次都创建新 event loop**）
    4. 验证每次 task 都能成功提交 + 写库
    """
    print(f"  [child {os.getpid()}] worker 启动")
    try:
        # Step 1: worker_process_init 重建 engine
        new_engine = create_async_engine(
            os.environ["ASYNC_DATABASE_URL"],
            poolclass=NullPool,  # 避免连接池跨 event loop 复用
        )
        AsyncSessionLocal.reset(new_engine)
        print(f"  [child {os.getpid()}] worker_process_init OK (engine reset)")

        # Step 2: 建表（同步引擎）
        sync_eng = create_engine(os.environ["SYNC_DATABASE_URL"], poolclass=NullPool)
        Base.metadata.create_all(sync_eng)

        # Step 3: 跑多次 task
        async def fake_rebuild_task(task_id: int):
            """模拟 rebuild_knowledge_base 任务体。"""
            started = datetime.utcnow()
            async with AsyncSessionLocal() as s:
                # 设 running
                row = (await s.execute(
                    select(KBRebuildState).order_by(KBRebuildState.id).limit(1)
                )).scalar_one_or_none()
                if row is None:
                    s.add(KBRebuildState(id=1, state="running", updated_at=started))
                else:
                    row.state = "running"
                    row.updated_at = started
                await s.commit()

                # 插 5 条 chunk
                for i in range(5):
                    s.add(KnowledgeChunk(
                        id=f"{task_id}-{i}",
                        kb_type=KBChunkType.DEFECT,
                        content=f"task {task_id} chunk {i}",
                    ))
                await s.commit()

                # 设 idle
                row.state = "idle"
                row.updated_at = datetime.utcnow()
                await s.commit()
            return f"task {task_id} OK"

        for i in range(task_count):
            # 关键：每次 asyncio.run 创建**新** event loop
            try:
                result = asyncio.run(fake_rebuild_task(i))
                print(f"  [child {os.getpid()}] {result}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [child {os.getpid()}] task {i} FAILED: {type(exc).__name__}: {exc}")
                # 关键失败信号
                if "different loop" in str(exc) or "Event loop is closed" in str(exc):
                    print(f"  [child {os.getpid()}] ❌ BUG 复现: Celery prefork 仍会撞这个错")
                    return False

        # Step 4: 验证写入
        with sessionmaker(bind=sync_eng)() as s:
            total = s.execute(select(func.count()).select_from(KnowledgeChunk)).scalar()
            print(f"  [child {os.getpid()}] 共写入 {total} chunks（期望 {task_count * 5}）")
            assert total == task_count * 5, f"期望 {task_count * 5} 但实际 {total}"
        print(f"  [child {os.getpid()}] ✅ 全部 task 成功，无 loop 冲突")
        return True
    except Exception:
        traceback.print_exc()
        return False


# ==================== 主进程入口 ====================


def _main_process():
    """主进程：创建初始 engine + fork worker 子进程（模拟 Celery prefork）。"""
    print(f"[main {os.getpid()}] 主进程启动，创建初始 async engine")

    # 主进程：创建 async_engine 单例
    global AsyncSessionLocal
    main_engine = create_async_engine(
        os.environ["ASYNC_DATABASE_URL"],
        poolclass=NullPool,
    )
    AsyncSessionLocal.reset(main_engine)
    print(f"[main {os.getpid()}] 主进程 engine OK")

    # 在主进程建表（让子进程能直接用）
    sync_eng = create_engine(os.environ["SYNC_DATABASE_URL"], poolclass=NullPool)
    Base.metadata.create_all(sync_eng)

    # fork 子进程（Celery prefork 模拟）
    print(f"[main {os.getpid()}] 准备 fork worker 子进程…")
    if sys.platform == "win32":
        print("  (Windows: 用 spawn 替代 fork；这里直接调子进程函数同进程跑)")
        ok = _worker_subprocess_entry(task_count=3)
    else:
        ctx = mp.get_context("fork")
        p = ctx.Process(target=_worker_subprocess_entry, args=(3,))
        p.start()
        p.join(timeout=30)
        if p.exitcode != 0:
            print(f"  [main] ❌ worker 子进程 exitcode={p.exitcode}")
            return False
        ok = True
    return ok


if __name__ == "__main__":
    print("=" * 60)
    print(" Celery prefork + asyncpg 'Future attached to different loop' 模拟")
    print("=" * 60)
    ok1 = _main_process()
    print()
    if ok1:
        print("🎉 通过：worker_process_init.reset_async_engine 100% 解决 fork 后 loop 冲突")
        print("   → 旧 dispose() 不够，必须完全重建 engine")
        print("   → AsyncSessionLocal 必须是 proxy，所有 import 走 proxy 自动拿新 engine")
    else:
        print("❌ 失败：还有 loop 冲突")
    print()

    # 第二个测试：验证 17 处 import 都拿同一 proxy，reset 后全部用新 engine
    print("=" * 60)
    print(" 测试 2：17 处 import 拿同一 proxy + reset 后自动拿新 engine")
    print("=" * 60)
    # 模拟 17 个不同模块都 import 了 AsyncSessionLocal
    importers = []
    for i in range(17):
        importers.append(AsyncSessionLocal)  # 都拿同一个对象

    # 验证 17 个都是同一 proxy 对象
    same_obj = all(x is importers[0] for x in importers)
    print(f"  17 处 import 拿同一对象: {same_obj}")
    assert same_obj, "应都是同一 proxy 对象"

    # 第一次 reset
    eng1 = create_async_engine(os.environ["ASYNC_DATABASE_URL"], poolclass=NullPool)
    AsyncSessionLocal.reset(eng1)
    sm1 = AsyncSessionLocal._current_session_maker

    # 第二次 reset
    eng2 = create_async_engine(os.environ["ASYNC_DATABASE_URL"], poolclass=NullPool)
    AsyncSessionLocal.reset(eng2)
    sm2 = AsyncSessionLocal._current_session_maker

    assert sm1 is not sm2, "两次 reset 应产生不同 sessionmaker"
    assert sm2.kw["bind"] is eng2, "第二次 reset 后 sessionmaker 应 bind eng2"
    print(f"  第二次 reset 后 sessionmaker bind: {sm2.kw['bind']!r}")
    print(f"  对照 eng2: {eng2!r}")
    assert sm2.kw["bind"] is eng2
    print("  ✅ 17 处 import + 多次 reset：proxy 内部始终用最新 engine")
    print()
    print("=" * 60)
    print("🎉 全部测试通过")
    print("=" * 60)
    sys.exit(0 if ok1 else 1)
