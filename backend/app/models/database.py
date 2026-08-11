"""
AI 自动化测试平台 — 数据库模型
"""

from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, JSON, Float,
    ForeignKey, Enum as SAEnum, Index, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship
import uuid

Base = declarative_base()


# ==================== 枚举类型 ====================

class SourceType(PyEnum):
    GITHUB = "github"
    SVN = "svn"
    UPLOAD = "upload"

class TestStatus(PyEnum):
    PENDING = "pending"
    PULLING = "pulling"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    EXECUTING = "executing"
    ANALYZING_DEFECTS = "analyzing_defects"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class DefectSeverity(PyEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

class DefectType(PyEnum):
    BUSINESS = "business"
    PROGRAM = "program"
    PERFORMANCE = "performance"
    INTEGRATION = "integration"
    SECURITY = "security"

class ModelProvider(PyEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"
    LOCAL = "local"

class UserRole(PyEnum):
    SUPER_ADMIN = "super_admin"   # 超级管理员：所有管理操作立即生效
    ADMIN = "admin"               # 管理员：管理类操作需审核员审批
    TEST_MANAGER = "test_manager" # 测试经理
    TESTER = "tester"
    DEVELOPER = "developer"
    AUDITOR = "auditor"           # 审核员：审批管理类变更申请
    VIEWER = "viewer"


# ==================== 用户与权限 ====================

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole, name="userrole"), default=UserRole.VIEWER, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    test_runs = relationship("TestRun", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")


class Project(Base):
    """项目表 — 多租户隔离"""
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source_type = Column(SAEnum(SourceType, name="sourcetype"), nullable=False)
    source_config = Column(JSONB, default={})  # 仓库地址、分支等配置
    quality_gate_config = Column(JSONB, default={})  # 质量门禁规则
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    test_runs = relationship("TestRun", back_populates="project")


# ==================== AI 模型配置 ====================

class AIModelConfig(Base):
    """AI 模型配置表"""
    __tablename__ = "ai_model_configs"

    id = Column(String(64), primary_key=True)  # config_id
    name = Column(String(200), nullable=False)
    provider = Column(SAEnum(ModelProvider, name="modelprovider"), nullable=False)
    api_base_url = Column(String(500), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)  # AES-256 加密
    model_name = Column(String(200), nullable=False)
    api_version = Column(String(50), nullable=True)
    max_tokens = Column(Integer, default=4096)
    temperature = Column(Float, default=0.3)
    timeout = Column(Integer, default=120)
    max_retries = Column(Integer, default=3)
    use_cases = Column(JSONB, default=[])  # ["code_analysis", "case_generation", ...]
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    is_fallback = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelRouting(Base):
    """模型路由配置 — 按场景分配模型"""
    __tablename__ = "model_routing"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_analysis_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=False)
    case_generation_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=False)
    defect_analysis_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=False)
    fix_suggestion_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=False)
    fallback_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==================== 测试任务 ====================

class TestRun(Base):
    """测试任务表"""
    __tablename__ = "test_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # 数据源信息
    source_type = Column(SAEnum(SourceType, name="sourcetype"), nullable=False)
    source_ref = Column(String(500))  # repo URL / SVN path / upload filename
    branch = Column(String(200))
    commit_sha = Column(String(40))  # Git commit / SVN revision
    commit_message = Column(Text)

    # 任务状态
    status = Column(SAEnum(TestStatus, name="teststatus"), default=TestStatus.PENDING, nullable=False)
    progress = Column(Integer, default=0)  # 0-100
    error_message = Column(Text)

    # 时间
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 代码分析结果（JSON）
    analysis_result = Column(JSONB, default={})
    # 快照 ID
    snapshot_id = Column(String(64))

    # 关系
    project = relationship("Project", back_populates="test_runs")
    user = relationship("User", back_populates="test_runs")
    test_cases = relationship("TestCase", back_populates="test_run")
    test_results = relationship("TestResult", back_populates="test_run")
    defects = relationship("Defect", back_populates="test_run")
    report = relationship("TestReport", back_populates="test_run", uselist=False)

    __table_args__ = (
        Index("idx_test_runs_project_status", "project_id", "status"),
        Index("idx_test_runs_created", "created_at"),
    )


# ==================== 测试用例与结果 ====================

class TestCase(Base):
    """测试用例表"""
    __tablename__ = "test_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=False)

    # 用例信息
    case_type = Column(String(50), nullable=False)  # api / performance / integration
    case_name = Column(String(500), nullable=False)
    description = Column(Text)

    # 用例数据
    request_data = Column(JSONB, nullable=False)  # 请求方法、URL、参数、头、体
    expected_result = Column(JSONB)  # 预期结果
    validation_rules = Column(JSONB)  # 校验规则

    # 优先级
    priority = Column(String(10), default="P2")  # P0-P3

    # 关联接口
    api_path = Column(String(500))
    http_method = Column(String(10))

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    test_run = relationship("TestRun", back_populates="test_cases")
    result = relationship("TestResult", back_populates="test_case", uselist=False)

    __table_args__ = (
        Index("idx_test_cases_run_type", "test_run_id", "case_type"),
    )


class TestResult(Base):
    """测试结果表"""
    __tablename__ = "test_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=False)
    test_case_id = Column(UUID(as_uuid=True), ForeignKey("test_cases.id"), nullable=False)

    # 执行结果
    is_passed = Column(Boolean, nullable=False)
    status_code = Column(Integer)  # HTTP 状态码
    response_body = Column(JSONB)
    response_time_ms = Column(Float)  # 响应时间（毫秒）

    # 性能指标（性能测试专用）
    tps = Column(Float)
    qps = Column(Float)
    error_rate = Column(Float)
    concurrent_users = Column(Integer)

    # 错误信息
    error_message = Column(Text)
    error_trace = Column(Text)

    executed_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    test_run = relationship("TestRun", back_populates="test_results")
    test_case = relationship("TestCase", back_populates="result")

    __table_args__ = (
        Index("idx_test_results_run_passed", "test_run_id", "is_passed"),
    )


# ==================== 缺陷 ====================

class Defect(Base):
    """缺陷表"""
    __tablename__ = "defects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=False)
    test_case_id = Column(UUID(as_uuid=True), ForeignKey("test_cases.id"), nullable=True)

    # 缺陷信息
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    defect_type = Column(SAEnum(DefectType, name="defecttype"), nullable=False)
    severity = Column(SAEnum(DefectSeverity, name="defectseverity"), nullable=False)

    # 复现路径
    reproduce_steps = Column(JSONB)

    # AI 分析
    root_cause = Column(Text)
    fix_suggestion = Column(Text)

    # 状态
    is_resolved = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    test_run = relationship("TestRun", back_populates="defects")

    __table_args__ = (
        Index("idx_defects_run_severity", "test_run_id", "severity"),
    )


# ==================== 报告 ====================

class TestReport(Base):
    """测试报告表"""
    __tablename__ = "test_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=False)

    # 报告信息
    report_data = Column(JSONB, nullable=False)  # 完整报告 JSON
    html_path = Column(String(500))  # HTML 文件路径 (MinIO)
    pdf_path = Column(String(500))  # PDF 文件路径 (MinIO)
    share_token = Column(String(64), unique=True)  # 分享链接 token

    # 质量评分
    quality_score = Column(Integer)  # 0-100

    # 质量门禁结果
    gate_passed = Column(Boolean)
    gate_details = Column(JSONB)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    test_run = relationship("TestRun", back_populates="report")


# ==================== 审计日志 ====================

class AuditLog(Base):
    """审计日志表"""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)  # create_test_run, delete_project, etc.
    resource_type = Column(String(50))  # project, test_run, model_config, etc.
    resource_id = Column(String(100))
    details = Column(JSONB)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_logs_user_created", "user_id", "created_at"),
        Index("idx_audit_logs_action", "action"),
    )


# ==================== 站内通知 ====================

class Notification(Base):
    """站内通知表 — 用户消息中心"""
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False, default="")
    # 通知类型：system / test / defect / gate
    type = Column(String(50), nullable=False, default="system")
    is_read = Column(Boolean, default=False, nullable=False)
    related_url = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_notifications_user_read", "user_id", "is_read"),
        Index("idx_notifications_user_created", "user_id", "created_at"),
    )


# ==================== 变更审批 ====================

class ChangeRequest(Base):
    """
    变更申请表 — 管理类操作的审批流。

    ADMIN 发起的新建用户 / 删除用户 / 修改角色操作会先落一条 pending 记录，
    由 AUDITOR 或 SUPER_ADMIN 审批通过后才真正生效。
    SUPER_ADMIN 发起的操作立即生效，不产生此记录。
    """
    __tablename__ = "change_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(String(50), nullable=False)          # create_user | delete_user | change_role
    payload = Column(JSONB, default={})                # create_user: {username,email,hashed_password,role}; change_role: {role}
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    target_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="pending", nullable=False)  # pending | approved | rejected
    review_note = Column(Text)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime)

    __table_args__ = (
        Index("idx_change_requests_status_created", "status", "created_at"),
    )


# ==================== 数据库初始化 ====================

async def init_db():
    """
    初始化数据库 — 创建全部表结构。

    使用 app.utils.database 中的共享异步引擎，确保全应用连接池统一管理。
    生产环境推荐使用 Alembic 迁移管理表结构（alembic upgrade head），
    此方法作为开发环境的快捷初始化途径。
    """
    from loguru import logger
    from app.utils.database import async_engine

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables created (via Base.metadata.create_all)")

    # 旧库补齐 userrole 枚举新增值（新库由 create_all 一次建全，此处为幂等兜底）。
    #
    # 【必须按枚举成员名补值，不能按值补】
    # SQLAlchemy 的 SAEnum(UserRole) 默认持久化的是成员名 member.name
    # （SUPER_ADMIN / TEST_MANAGER / AUDITOR，大写），而不是 member.value
    # （super_admin / test_manager / auditor，小写）。
    # 若这里补成小写，旧库的 userrole 仍然只有 ADMIN/TESTER/DEVELOPER/VIEWER 四个标签，
    # 随后 AuthService.init_default_admin() 执行
    #     WHERE users.role = 'SUPER_ADMIN'::userrole
    # 会被 PostgreSQL 拒绝（22P02 invalid input value for enum userrole），
    # 异常穿透 lifespan → uvicorn 启动失败 → 8000 端口无监听 → nginx 502。
    #
    # PostgreSQL 的 ALTER TYPE ... ADD VALUE 建议在事务外执行，故使用 AUTOCOMMIT；
    # DDL 不支持参数绑定，标签取自代码内枚举定义，为可信字面量，无注入风险。
    role_labels: tuple[str, ...] = tuple(member.name for member in UserRole)
    try:
        async with async_engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            for label in role_labels:
                try:
                    await autocommit_conn.execute(
                        text(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{label}'")
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to add enum label '{label}' to userrole: {e}. "
                        f"若角色相关接口报错，请执行 `docker compose down -v` 重建数据库。"
                    )
    except Exception as e:
        # 整段为幂等兜底，连接层异常也不允许打断应用启动
        logger.warning(f"Skip userrole enum sync (connection error): {e}")
    else:
        logger.info(f"UserRole enum labels ensured: {', '.join(role_labels)}")
