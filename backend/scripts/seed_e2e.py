"""E2E 种子脚本：一次性造出可验收全平台的最小数据集。

幂等：重复运行不会破坏现有数据（按业务唯一键 SELECT-then-INSERT）。
可重入：dev/staging/prod 都可跑。

生成数据：
    1. Project「e2e-demo-project」+ TestRun（已完成，run1）
    2. 10 条 TestCase
    3. 5 条 Defect（含根因 + 修复建议，让 RAG 有料）
    4. 30 条 KnowledgeTerm（业务术语，知识库 RAG 主入口）
    5. 10 条 ApiEndpoint（GET/POST/PUT/DELETE 混合）
    6. 10 条 TestResult（run1，约 1/3 失败）+ 1 份 TestReport（供「报告AI分析」演示）
    7. 第二个 TestRun（run2，复用 run1 用例 id 造差异结果，供「执行对比」演示）

跑完后可验收：
    - 知识库 RAG：点"一键重建" → 重建完成后切片数 > 0
    - 检索预览：输入 "登录失败" → 应命中 defect 类切片
    - 接口列表：API endpoints 出现在「接口资产」页
    - 测试任务：项目 test_run 列表里看到 e2e-demo 的记录
    - 报告AI分析：选 e2e-demo-project → 报告/结果/对比Run 下拉框已填充，可直接发起分析

使用：
    cd backend
    python -m scripts.seed_e2e

依赖：app 环境变量已配（DATABASE_URL 等），无其他外部依赖。
"""
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Optional

# 让脚本可独立运行：把 backend/ 加进 sys.path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from loguru import logger  # noqa: E402

from app.utils.database import AsyncSessionLocal  # noqa: E402
from app.models.database import (  # noqa: E402
    ApiEndpoint,
    Defect,
    DefectSeverity,
    DefectType,
    KnowledgeTerm,
    Project,
    SourceType,
    TestCase,
    TestReport,
    TestResult,
    TestRun,
    TestStatus,
    User,
    UserRole,
)


# ============ 数据集（30 条业务术语 + 5 条历史缺陷 + 10 条接口 + 10 条用例） ============

TERMS: list[dict] = [
    # 鉴权与会话（8）
    {"term": "登录", "aliases": ["登陆", "login"], "technical_meaning": "用户凭据校验与会话建立", "domain": "鉴权"},
    {"term": "鉴权", "aliases": ["身份验证", "authentication"], "technical_meaning": "验证调用方身份合法性的过程", "domain": "鉴权"},
    {"term": "会话", "aliases": ["session"], "technical_meaning": "服务端维持的登录态；常见载体 Cookie/Token", "domain": "鉴权"},
    {"term": "Token", "aliases": ["令牌"], "technical_meaning": "无状态鉴权凭证；常用 JWT", "domain": "鉴权"},
    {"term": "Cookie", "aliases": [], "technical_meaning": "浏览器自动携带的小型 KV 凭证", "domain": "鉴权"},
    {"term": "幂等", "aliases": ["幂等性", "idempotent"], "technical_meaning": "同一请求多次提交结果一致；POST 需带幂等键", "domain": "分布式"},
    {"term": "事务", "aliases": ["transaction"], "technical_meaning": "一组原子操作；满足 ACID", "domain": "数据库"},
    {"term": "隔离级别", "aliases": [], "technical_meaning": "RR/RC 等并发控制强度", "domain": "数据库"},
    # 数据库（6）
    {"term": "索引", "aliases": [], "technical_meaning": "B+Tree 等结构加速查询；过多影响写入", "domain": "数据库"},
    {"term": "慢查询", "aliases": [], "technical_meaning": "执行时间超过阈值的 SQL，需 explain 优化", "domain": "数据库"},
    {"term": "连接池", "aliases": [], "technical_meaning": "复用数据库连接，避免频繁建连", "domain": "数据库"},
    {"term": "死锁", "aliases": [], "technical_meaning": "两个事务互相持有对方等待的资源", "domain": "数据库"},
    {"term": "主键", "aliases": ["PK"], "technical_meaning": "唯一标识记录的列", "domain": "数据库"},
    {"term": "外键", "aliases": ["FK"], "technical_meaning": "引用其他表主键的列；保证引用完整性", "domain": "数据库"},
    # 缓存与高可用（6）
    {"term": "缓存击穿", "aliases": [], "technical_meaning": "热点 key 失效瞬间大量请求直击 DB", "domain": "缓存"},
    {"term": "缓存雪崩", "aliases": [], "technical_meaning": "大量 key 同时过期导致请求全打到 DB", "domain": "缓存"},
    {"term": "缓存穿透", "aliases": [], "technical_meaning": "查询不存在的数据绕过缓存", "domain": "缓存"},
    {"term": "最终一致", "aliases": [], "technical_meaning": "分布式系统中允许短暂不一致、最终同步", "domain": "分布式"},
    {"term": "限流", "aliases": [], "technical_meaning": "限制单位时间请求数；令牌桶/漏桶", "domain": "高可用"},
    {"term": "熔断", "aliases": [], "technical_meaning": "下游故障时上游快速失败，避免雪崩", "domain": "高可用"},
    # 接口与协议（5）
    {"term": "REST", "aliases": ["RESTful"], "technical_meaning": "资源导向的 HTTP 接口设计风格", "domain": "接口"},
    {"term": "HTTP状态码", "aliases": [], "technical_meaning": "2xx 成功 / 4xx 客户端错 / 5xx 服务端错", "domain": "接口"},
    {"term": "鉴权失败", "aliases": [], "technical_meaning": "HTTP 401；token 无效或过期", "domain": "鉴权"},
    {"term": "超时", "aliases": [], "technical_meaning": "请求超过预设时间；HTTP 504", "domain": "接口"},
    {"term": "重试", "aliases": [], "technical_meaning": "失败后自动重新发起；需配合幂等", "domain": "高可用"},
    # 性能与测试（5）
    {"term": "QPS", "aliases": ["每秒查询率"], "technical_meaning": "Queries Per Second", "domain": "性能"},
    {"term": "TPS", "aliases": ["每秒事务数"], "technical_meaning": "Transactions Per Second", "domain": "性能"},
    {"term": "P99", "aliases": [], "technical_meaning": "99% 请求延迟分位数；衡量长尾", "domain": "性能"},
    {"term": "灰度", "aliases": ["灰度发布"], "technical_meaning": "按比例放量新版本；降低爆炸半径", "domain": "发布"},
    {"term": "回归", "aliases": ["回归测试"], "technical_meaning": "新功能上线后跑老用例确保未破坏", "domain": "测试"},
]

DEFECTS: list[dict] = [
    {
        "title": "登录接口返回 500 但数据库连接池正常",
        "description": "POST /api/auth/login 在 14:00 后开始返回 500，监控显示 DB 连接池未耗尽",
        "defect_type": DefectType.PROGRAM,
        "severity": DefectSeverity.P0,
        "root_cause": "Redis 连接超时（默认 2s），高峰期会话缓存读超时导致 login 抛 UnhandledError",
        "fix_suggestion": "1) 调大 Redis 超时到 5s；2) 把 session 读改为可选；4) 加降级本地缓存",
        "api_path": "/api/auth/login",
        "http_method": "POST",
    },
    {
        "title": "订单详情页并发 503",
        "description": "GET /api/orders/{id} 在并发 50 时 50% 返回 503",
        "defect_type": DefectType.PERFORMANCE,
        "severity": DefectSeverity.P1,
        "root_cause": "未走缓存，每次都查 DB + 多次关联查询；热点订单 row-level lock 竞争",
        "fix_suggestion": "1) 加 Redis 缓存（key=order:{id}, TTL 30s）；2) 加读锁替代 row lock",
        "api_path": "/api/orders/{id}",
        "http_method": "GET",
    },
    {
        "title": "创建订单幂等键校验失效导致重复订单",
        "description": "POST /api/orders 带相同 Idempotency-Key 仍创建多笔订单",
        "defect_type": DefectType.PROGRAM,
        "severity": DefectSeverity.P0,
        "root_cause": "Idempotency-Key 仅在 Redis 存 60s，且只校验第一次；Redis 抖动后 key 丢失",
        "fix_suggestion": "1) Redis key TTL 延长到 24h；2) 落库兜底（idempotency_keys 表）",
        "api_path": "/api/orders",
        "http_method": "POST",
    },
    {
        "title": "支付回调与订单状态机不一致",
        "description": "支付平台回调成功但订单状态仍为 PENDING",
        "defect_type": DefectType.INTEGRATION,
        "severity": DefectSeverity.P0,
        "root_cause": "回调签名校验失败但未记日志，导致重试链路断开",
        "fix_suggestion": "1) 签名失败也写 audit_log；2) 增加监控；3) 3 次失败后人工介入",
        "api_path": "/api/payments/callback",
        "http_method": "POST",
    },
    {
        "title": "搜索结果分页总数错误",
        "description": "GET /api/products/search 返回 total=120 但实际只有 80 条",
        "defect_type": DefectType.PROGRAM,
        "severity": DefectSeverity.P2,
        "root_cause": "count(*) 与 limit/offset 查询之间有写入，count 不一致",
        "fix_suggestion": "改用子查询：SELECT * FROM (SELECT id, count(*) OVER() total FROM products WHERE ...) LIMIT/OFFSET",
        "api_path": "/api/products/search",
        "http_method": "GET",
    },
]

API_ENDPOINTS: list[dict] = [
    {"method": "POST", "path": "/api/auth/login", "summary": "用户登录", "description": "用户名密码登录，返回 access_token"},
    {"method": "POST", "path": "/api/auth/logout", "summary": "用户登出", "description": "销毁会话"},
    {"method": "GET",  "path": "/api/users/me", "summary": "获取当前用户", "description": "返回当前登录用户信息"},
    {"method": "POST", "path": "/api/orders", "summary": "创建订单", "description": "幂等创建订单，需 Idempotency-Key"},
    {"method": "GET",  "path": "/api/orders/{id}", "summary": "订单详情", "description": "根据 ID 查询订单"},
    {"method": "GET",  "path": "/api/products/search", "summary": "商品搜索", "description": "分页搜索商品"},
    {"method": "POST", "path": "/api/payments/callback", "summary": "支付回调", "description": "支付平台异步回调"},
    {"method": "PUT",  "path": "/api/users/{id}", "summary": "更新用户", "description": "更新用户信息"},
    {"method": "DELETE", "path": "/api/orders/{id}", "summary": "取消订单", "description": "取消未支付订单"},
    {"method": "GET",  "path": "/api/health", "summary": "健康检查", "description": "服务健康状态"},
]


# ============ 种子函数 ============

PROJECT_NAME = "e2e-demo-project"
TEST_RUN_NAME = "e2e-seed-run"


async def _get_or_create_project(db, owner_id: uuid.UUID) -> Project:
    """幂等：按 name 查找项目。"""
    row = (
        await db.execute(select(Project).where(Project.name == PROJECT_NAME))
    ).scalar_one_or_none()
    if row:
        logger.info(f"Project 已存在: {row.name} ({row.id})")
        return row
    p = Project(
        name=PROJECT_NAME,
        description="E2E 验收测试种子项目（由 seed_e2e.py 创建）",
        owner_id=owner_id,
        source_type=SourceType.UPLOAD,
        source_config={"seed": True},
    )
    db.add(p)
    await db.flush()
    logger.info(f"Project 创建: {p.name} ({p.id})")
    return p


async def _get_or_create_test_run(
    db, project_id: uuid.UUID, user_id: uuid.UUID, source_ref: str = TEST_RUN_NAME
) -> TestRun:
    """幂等：按 project+source_ref 查找 test_run。"""
    row = (
        await db.execute(
            select(TestRun).where(
                TestRun.project_id == project_id,
                TestRun.source_ref == source_ref,
            )
        )
    ).scalar_one_or_none()
    if row:
        logger.info(f"TestRun 已存在: {row.source_ref} ({row.id})")
        return row
    tr = TestRun(
        project_id=project_id,
        user_id=user_id,
        source_type=SourceType.UPLOAD,
        source_ref=source_ref,
        branch="seed",
        commit_sha="seed0001",
        commit_message="E2E seed run (seed_e2e.py)",
        status=TestStatus.COMPLETED,
        progress=100,
    )
    db.add(tr)
    await db.flush()
    logger.info(f"TestRun 创建: {tr.source_ref} ({tr.id})")
    return tr


async def _seed_results(db, run_id: uuid.UUID) -> int:
    """为指定 run 的每个用例造一条测试结果（幂等：run 已有结果则跳过）。

    部分用例失败（i%3==0），以便「失败分析」演示命中失败用例。
    """
    existing = (
        await db.execute(
            select(TestResult.id).where(TestResult.test_run_id == run_id)
        )
    ).first()
    if existing:
        logger.info(f"TestResult 已存在 (run={run_id})，跳过")
        return 0
    cases = (
        await db.execute(select(TestCase).where(TestCase.test_run_id == run_id))
    ).scalars().all()
    added = 0
    for i, c in enumerate(cases):
        passed = i % 3 != 0  # 约 1/3 失败
        db.add(
            TestResult(
                test_run_id=run_id,
                test_case_id=c.id,
                is_passed=passed,
                status_code=200 if passed else 500,
                response_body={"ok": passed, "case": c.case_name},
                response_time_ms=120.0 + i * 5,
                error_message=None if passed else "Internal Server Error: null pointer",
            )
        )
        added += 1
    await db.flush()
    logger.info(f"TestResult: +{added} (run={run_id})")
    return added


async def _seed_report(db, run_id: uuid.UUID) -> None:
    """为指定 run 造一份测试报告（幂等：run 已有报告则跳过）。"""
    existing = (
        await db.execute(
            select(TestReport).where(TestReport.test_run_id == run_id)
        )
    ).scalar_one_or_none()
    if existing:
        logger.info(f"TestReport 已存在 (run={run_id})，跳过")
        return
    report_data = {
        "summary": {"total": 10, "passed": 7, "failed": 3, "skipped": 0},
        "quality_score": 82,
        "gate_passed": True,
        "generated_at": "2026-08-26T10:00:00",
        "details": {
            "passed_cases": ["e2e-case-001", "e2e-case-002", "e2e-case-004"],
            "failed_cases": ["e2e-case-003", "e2e-case-006", "e2e-case-009"],
        },
    }
    db.add(
        TestReport(
            test_run_id=run_id,
            report_data=report_data,
            quality_score=82,
            gate_passed=True,
        )
    )
    await db.flush()
    logger.info(f"TestReport 创建 (run={run_id})")


async def _seed_compare_run(db, project_id: uuid.UUID, user_id: uuid.UUID, case_ids: list) -> TestRun:
    """造第二个 run（复用 run1 的 test_case_id 造结果），供「执行对比」演示命中差异。

    结果与 run1 故意不同（i%2==0 通过），这样对比能产出真实 diff。
    """
    run2 = await _get_or_create_test_run(
        db, project_id, user_id, source_ref="e2e-seed-run-2"
    )
    existing = (
        await db.execute(
            select(TestResult.id).where(TestResult.test_run_id == run2.id)
        )
    ).first()
    if existing:
        logger.info(f"对比 Run 结果已存在 (run={run2.id})，跳过")
        return run2
    for i, cid in enumerate(case_ids):
        passed = i % 2 == 0  # 与 run1 不同的通过模式
        db.add(
            TestResult(
                test_run_id=run2.id,
                test_case_id=cid,
                is_passed=passed,
                status_code=200 if passed else 503,
                response_body={"ok": passed, "case": str(cid)[:8]},
                response_time_ms=150.0 + i * 7,
                error_message=None if passed else "Service Unavailable",
            )
        )
    await db.flush()
    logger.info(f"对比 Run 结果: +{len(case_ids)} (run={run2.id})")
    return run2


async def _seed_terms(db) -> int:
    """幂等：按 term 查找。"""
    existing = set(
        (await db.execute(select(KnowledgeTerm.term))).scalars().all()
    )
    added = 0
    for t in TERMS:
        if t["term"] in existing:
            continue
        db.add(KnowledgeTerm(**t))
        added += 1
    await db.flush()
    logger.info(f"KnowledgeTerm: +{added} (total={len(TERMS)})")
    return added


async def _seed_endpoints(db, project_id: uuid.UUID) -> int:
    """幂等：按 project_id+method+path 唯一约束。"""
    added = 0
    for ep in API_ENDPOINTS:
        row = (
            await db.execute(
                select(ApiEndpoint).where(
                    ApiEndpoint.project_id == project_id,
                    ApiEndpoint.method == ep["method"],
                    ApiEndpoint.path == ep["path"],
                )
            )
        ).scalar_one_or_none()
        if row:
            continue
        db.add(ApiEndpoint(project_id=project_id, **ep))
        added += 1
    await db.flush()
    logger.info(f"ApiEndpoint: +{added} (total={len(API_ENDPOINTS)})")
    return added


async def _seed_test_cases(db, run_id: uuid.UUID) -> int:
    """幂等：按 test_run_id+case_name 查重。"""
    existing = set(
        (
            await db.execute(
                select(TestCase.case_name).where(TestCase.test_run_id == run_id)
            )
        ).scalars().all()
    )
    added = 0
    for i in range(1, 11):
        name = f"e2e-case-{i:03d}"
        if name in existing:
            continue
        # 把对应接口接到 ApiEndpoint 上（任意取一条同 method 的）
        ep = next((e for e in API_ENDPOINTS if e["method"] in ("GET", "POST")), API_ENDPOINTS[0])
        db.add(
            TestCase(
                test_run_id=run_id,
                case_type="api",
                case_name=name,
                description=f"E2E 种子用例 #{i}",
                request_data={
                    "method": ep["method"],
                    "url": ep["path"],
                    "headers": {"Content-Type": "application/json"},
                    "body": {},
                },
                expected_result={"status_code": 200},
                validation_rules=[{"field": "status_code", "op": "eq", "value": 200}],
                priority="P2",
                api_path=ep["path"],
                http_method=ep["method"],
            )
        )
        added += 1
    await db.flush()
    logger.info(f"TestCase: +{added} (total=10)")
    return added


async def _seed_defects(db, run_id: uuid.UUID) -> int:
    """幂等：按 test_run_id+title 查重。"""
    existing = set(
        (
            await db.execute(
                select(Defect.title).where(Defect.test_run_id == run_id)
            )
        ).scalars().all()
    )
    added = 0
    for d in DEFECTS:
        if d["title"] in existing:
            continue
        db.add(
            Defect(
                test_run_id=run_id,
                title=d["title"],
                description=d["description"],
                defect_type=d["defect_type"],
                severity=d["severity"],
                root_cause=d["root_cause"],
                fix_suggestion=d["fix_suggestion"],
                is_resolved=False,
            )
        )
        added += 1
    await db.flush()
    logger.info(f"Defect: +{added} (total={len(DEFECTS)})")
    return added


async def main() -> None:
    """主入口。"""
    logger.info("=" * 60)
    logger.info("E2E 种子脚本启动")
    logger.info("=" * 60)

    async with AsyncSessionLocal() as db:
        # 1. 找到第一个 admin 用户（owner）
        admin = (
            await db.execute(
                select(User).where(
                    User.role.in_(
                        [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER]
                    )
                ).limit(1)
            )
        ).scalar_one_or_none()
        if admin is None:
            logger.error(
                "未找到任何 admin 用户。请先通过 init_default_admin 种子账号登录。"
            )
            sys.exit(1)
        logger.info(f"使用 admin 用户: {admin.username} ({admin.id})")

        # 2. Project
        project = await _get_or_create_project(db, admin.id)

        # 3. TestRun（run1）
        test_run = await _get_or_create_test_run(db, project.id, admin.id)

        # 4. 各项数据（顺序无关）
        await _seed_terms(db)
        await _seed_endpoints(db, project.id)
        await _seed_test_cases(db, test_run.id)
        await _seed_defects(db, test_run.id)

        # 5. 报告分析演示数据：报告 + 结果（run1）
        await _seed_results(db, test_run.id)
        await _seed_report(db, test_run.id)

        # 6. 执行对比演示数据：第二个 run（复用 run1 的用例 id 造差异结果）
        case_ids = (
            await db.execute(
                select(TestCase.id).where(TestCase.test_run_id == test_run.id)
            )
        ).scalars().all()
        compare_run = await _seed_compare_run(db, project.id, admin.id, case_ids)

        # 7. 提交
        await db.commit()
        logger.info("=" * 60)
        logger.info("✅ E2E 种子脚本完成")
        logger.info(f"   Project: {project.name} ({project.id})")
        logger.info(f"   TestRun: {test_run.source_ref} ({test_run.id})")
        logger.info(f"   对比Run: {compare_run.source_ref} ({compare_run.id})")
        logger.info("=" * 60)
        logger.info("下一步：")
        logger.info("  · 知识库RAG 页 → 重建 → 应有非 0 切片数")
        logger.info("  · 报告AI分析 页 → 选 e2e-demo-project → 报告/结果/对比Run 下拉框应已填充")


if __name__ == "__main__":
    asyncio.run(main())