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


# ==================== 能力12 枚举 ====================

class KBChunkType(PyEnum):
    """知识库切片类型（SAEnum 必须显式 name=，避开 PG 枚举名大小写坑）"""
    DEFECT = "defect"
    CASE = "case"
    DOC = "doc"
    TERM = "term"


# ==================== 能力3/4 枚举 ====================


class CaseAssetStatus(PyEnum):
    """用例资产状态 — 草稿 / 已采纳 / 已废弃（接纳闭环）"""
    DRAFT = "draft"
    ADOPTED = "adopted"
    DEPRECATED = "deprecated"


class CaseSource(PyEnum):
    """用例资产来源 — AI 生成 / 人工录入"""
    AI_GENERATED = "ai_generated"
    MANUAL = "manual"


class ScenarioStatus(PyEnum):
    """测试场景状态 — 草稿 / 已编排 / 已采纳"""
    DRAFT = "draft"
    ORCHESTRATED = "orchestrated"
    ADOPTED = "adopted"


# ==================== 能力5/6/7/8/9 枚举 ====================


class ScriptType(PyEnum):
    """脚本类型 — 统一脚本生成入口的 type 参数（能力5/6/7）"""
    PRE_SCRIPT = "pre_script"
    POST_SCRIPT = "post_script"
    SQL_SCRIPT = "sql_script"


class ScheduledTaskStatus(PyEnum):
    """定时任务状态（能力8）"""
    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"


class ScheduledTaskTargetType(PyEnum):
    """定时任务关联对象类型（能力8）"""
    SCENARIO = "scenario"
    CASE_COLLECTION = "case_collection"


class AnalysisType(PyEnum):
    """AI 分析类型（能力9）"""
    FAILURE = "failure"
    REPORT_SUMMARY = "report_summary"
    COMPARE = "compare"


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
    # 能力1/2 新增插槽：刻意 nullable=True，老库已有行无需补默认值；为 NULL 时运行时降级
    doc_parse_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=True)
    doc_review_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=True)
    # 能力4 新增插槽：场景编排模型，刻意 nullable=True，老库已有行无需补默认值
    scenario_orchestration_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=True)
    # 能力5/6/7/9 新增插槽：脚本生成、SQL 生成、报告分析，nullable=True
    script_generation_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=True)
    sql_generation_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=True)
    report_analysis_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=True)
    fallback_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=False)
    # 能力12：嵌入模型插槽（nullable=True，老库兼容）
    embedding_model_id = Column(String(64), ForeignKey("ai_model_configs.id"), nullable=True)
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


# ==================== 接口文档资产（能力1：AI 解析接口文档导入 / 能力2：AI 评审接口文档） ====================

class DocFormat(PyEnum):
    """接口文档格式（OPENAPI 含 swagger2 / openapi3；TXT 为纯文本描述）"""
    OPENAPI = "openapi"
    HAR = "har"
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"


class DocStatus(PyEnum):
    """文档解析状态机：PARSING → PARSED / FAILED"""
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"


class EndpointSource(PyEnum):
    """接口资产来源 — 本轮仅 DOC_IMPORT，预留 CODE_ANALYSIS 供用例生成链路消费"""
    DOC_IMPORT = "doc_import"
    CODE_ANALYSIS = "code_analysis"


class ReviewEngine(PyEnum):
    """评审引擎：AI 模型评审 / 规则兜底评审"""
    AI = "ai"
    RULE = "rule"


class InterfaceDoc(Base):
    """接口文档记录 — 一次上传/解析的文档实体（能力1）"""
    __tablename__ = "interface_docs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    uploader_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    filename = Column(String(500), nullable=False)
    format = Column(SAEnum(DocFormat, name="docformat"), nullable=False)
    storage_key = Column(String(500), nullable=False)  # 本地卷路径 /app/data/uploads/docs/<uuid>.<ext>
    minio_key = Column(String(500), nullable=True)      # MinIO 镜像对象名，失败为 NULL
    raw_text = Column(Text, nullable=True)              # docx/pdf 抽取全文，缓存避免重复抽取
    status = Column(SAEnum(DocStatus, name="docstatus"), default=DocStatus.PARSING, nullable=False)
    parse_engine = Column(String(20), nullable=True)    # rule / ai / rule_degraded
    api_spec_json = Column(JSONB, default={})           # 解析结果（文档级 ApiSpec）
    error = Column(Text, nullable=True)
    file_size = Column(Integer, default=0)
    sha256 = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_interface_docs_project", "project_id"),
        Index("idx_interface_docs_status", "status"),
    )


class ApiEndpoint(Base):
    """接口资产 — 从文档导入的可复用接口（核心资产，能力1落库 / 能力2评审对象）"""
    __tablename__ = "api_endpoints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("interface_docs.id"), nullable=True)
    method = Column(String(10), nullable=False)            # 大写 GET/POST/...
    path = Column(String(500), nullable=False)             # 归一化路径
    summary = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    params = Column(JSONB, default=[])                      # [{name, in, type, required, description, example}]
    request_body = Column(JSONB, default={})               # {content_type, required, schema, example}
    responses = Column(JSONB, default=[])                  # [{status_code, description, content_type, schema, example}]
    auth_required = Column(Boolean, default=False)
    version = Column(Integer, default=1)                   # 每次 upsert 覆盖 +1
    is_active = Column(Boolean, default=True)
    source = Column(SAEnum(EndpointSource, values_callable=lambda x: [e.value for e in x], name="endpointsource"), default=EndpointSource.DOC_IMPORT, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "method", "path", name="uq_api_endpoints_project_method_path"),
        Index("idx_api_endpoints_project_method", "project_id", "method"),
        Index("idx_api_endpoints_doc", "doc_id"),
    )


class DocReview(Base):
    """接口文档评审结果（能力2）"""
    __tablename__ = "doc_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("interface_docs.id"), nullable=True)  # 允许独立接口级评审无来源 doc
    endpoint_id = Column(UUID(as_uuid=True), ForeignKey("api_endpoints.id"), nullable=True)  # 指定接口评审时填充
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    score = Column(Integer, nullable=False, default=0)     # 1-5，后端按权重复算
    scores_json = Column(JSONB, default={})                # 各维度分 {basic_info, request_params, response_definition, security_auth}
    dimensions = Column(JSONB, default=[])                 # 四维明细 [{dimension, score, comment}]
    suggestions = Column(JSONB, default=[])               # 问题建议 [{dimension, target, severity, issue, root_cause, suggestion, example}]
    engine = Column(SAEnum(ReviewEngine, name="reviewengine"), default=ReviewEngine.RULE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_doc_reviews_doc", "doc_id"),
        Index("idx_doc_reviews_project", "project_id"),
    )


# ==================== 需求文档资产（能力10：需求文档解析） ====================


class RequirementDoc(Base):
    """需求文档记录 — 一次上传/解析的需求文档实体"""

    __tablename__ = "requirement_docs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    uploader_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    filename = Column(String(500), nullable=False)
    format = Column(SAEnum(DocFormat, name="docformat"), nullable=False)
    storage_key = Column(String(500), nullable=False)  # 本地卷路径 /app/data/uploads/requirements/<uuid>.<ext>
    raw_text = Column(Text, nullable=True)             # docx/pdf 抽取全文缓存
    status = Column(SAEnum(DocStatus, name="docstatus"), default=DocStatus.PARSING, nullable=False)
    parse_engine = Column(String(20), nullable=True)    # ai / rule_degraded
    requirements_json = Column(JSONB, default={})      # 解析结果（RequirementSpec 序列化）
    error = Column(Text, nullable=True)
    file_size = Column(Integer, default=0)
    sha256 = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_requirement_docs_project", "project_id"),
        Index("idx_requirement_docs_status", "status"),
    )


# ==================== 代码覆盖率报告（能力11：行/分支覆盖率采集） ====================


class CoverageTool(PyEnum):
    """覆盖率工具"""
    COVERAGE_PY = "coverage.py"   # Python, 输出 Cobertura XML
    JACOCO = "jacoco"             # Java, 输出 JaCoCo XML
    ISTANBUL = "istanbul"         # Node, 输出 lcov / cobertura
    COBERTURA = "cobertura"       # 通用 Cobertura XML


class CoverageSource(PyEnum):
    """覆盖率来源"""
    AUTO = "auto"     # 平台启动 SUT 时自动挂载探针采集
    UPLOAD = "upload" # 用户手动上传报告


class CoverageReport(Base):
    """覆盖率报告 — 一次测试运行 / 一次上传的覆盖率快照"""

    __tablename__ = "coverage_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    test_run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=True)
    uploader_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    tool = Column(SAEnum(CoverageTool, name="coveragetool"), nullable=False)
    language = Column(String(50), nullable=True)  # python / java / javascript ...
    source = Column(SAEnum(CoverageSource, name="coveragesource"), default=CoverageSource.UPLOAD, nullable=False)

    # 汇总指标（百分比，0-100，保留 2 位）
    line_rate = Column(Float, default=0.0)       # 行覆盖率 %
    branch_rate = Column(Float, default=0.0)     # 分支覆盖率 %
    total_lines = Column(Integer, default=0)
    covered_lines = Column(Integer, default=0)
    total_branches = Column(Integer, default=0)
    covered_branches = Column(Integer, default=0)

    files_json = Column(JSONB, default=[])       # 文件级明细 [{path, line_rate, branch_rate, total_lines, covered_lines}]
    storage_key = Column(String(500), nullable=True)  # 原始报告文件路径（上传时）
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_coverage_reports_project", "project_id"),
        Index("idx_coverage_reports_test_run", "test_run_id"),
    )



# ==================== 能力3：用例资产表（接纳闭环） ====================


class TestCaseAsset(Base):
    """用例资产表 — 可被反复采纳/编辑/执行的用例资产（与执行实例 TestCase 解耦）"""
    __tablename__ = "test_case_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    endpoint_id = Column(UUID(as_uuid=True), ForeignKey("api_endpoints.id"), nullable=True)
    case_type = Column(String(50), nullable=False)  # positive / negative / boundary / exception
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    request_data = Column(JSONB, nullable=False, default={})  # {method, url, headers, body, params}
    expected_result = Column(JSONB, nullable=True)            # {status_code, assertions:[...]}
    priority = Column(String(10), default="P2")               # P0-P3
    status = Column(SAEnum(CaseAssetStatus, values_callable=lambda x: [e.value for e in x], name="caseassetstatus"), default=CaseAssetStatus.DRAFT, nullable=False)
    source = Column(SAEnum(CaseSource, values_callable=lambda x: [e.value for e in x], name="casesource"), default=CaseSource.AI_GENERATED, nullable=False)
    # 能力5/6/7：脚本字段
    pre_script = Column(Text, nullable=True)
    post_script = Column(Text, nullable=True)
    sql_script = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_test_case_assets_project", "project_id"),
        Index("idx_test_case_assets_project_status", "project_id", "status"),
        Index("idx_test_case_assets_endpoint", "endpoint_id"),
    )


# ==================== 能力4：测试场景表（steps JSONB 单表） ====================


class Scenario(Base):
    """测试场景表 — 自然语言编排出的多步串联场景（steps 以 JSONB 存于单表）"""
    __tablename__ = "scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    nl_input = Column(Text, nullable=False)  # 用户自然语言场景描述（编排输入）
    status = Column(SAEnum(ScenarioStatus, values_callable=lambda x: [e.value for e in x], name="scenariostatus"), default=ScenarioStatus.DRAFT, nullable=False)
    # 每步结构：{step_order, endpoint_id, action_desc, method, url, extract, inject, depend_on_step, request}
    steps = Column(JSONB, default=list)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_scenarios_project", "project_id"),
        Index("idx_scenarios_project_status", "project_id", "status"),
    )


# ==================== 能力5/6/7：脚本生成记录 ====================


class ScriptGenerationRecord(Base):
    """脚本生成记录（审计） — 能力5/6/7"""
    __tablename__ = "script_generation_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    script_type = Column(SAEnum(ScriptType, name="scripttype"), nullable=False)
    nl_input = Column(Text, nullable=False)
    context = Column(JSONB, default={})
    generated_script = Column(Text, nullable=False)
    model_used = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_script_gen_records_project_created", "project_id", "created_at"),
        Index("idx_script_gen_records_type", "script_type"),
    )


# ==================== 能力7：数据库连接配置 ====================


class DatabaseConnection(Base):
    """数据库连接配置 — 能力7（密码加密存储）"""
    __tablename__ = "database_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    name = Column(String(200), nullable=False)
    db_type = Column(String(20), default="postgresql")
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    database = Column(String(200), nullable=False)
    username = Column(String(200), nullable=False)
    password_encrypted = Column(Text, nullable=False)  # AES-256 加密
    extra_config = Column(JSONB, default={})
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_database_connections_project", "project_id"),
    )


# ==================== 能力8：定时任务 ====================


class ScheduledTask(Base):
    """定时任务 — 能力8"""
    __tablename__ = "scheduled_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    nl_schedule = Column(Text)
    cron_expression = Column(String(100), nullable=False)
    target_type = Column(SAEnum(ScheduledTaskTargetType, name="scheduledtasktargettype"), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=True)
    target_config = Column(JSONB, default={})
    env_config = Column(JSONB, default={})
    status = Column(SAEnum(ScheduledTaskStatus, name="scheduledtaskstatus"), default=ScheduledTaskStatus.ACTIVE, nullable=False)
    last_run_at = Column(DateTime)
    last_run_status = Column(String(20))
    next_run_at = Column(DateTime)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_scheduled_tasks_project_status", "project_id", "status"),
    )


class ScheduledTaskRun(Base):
    """定时任务执行历史 — 能力8"""
    __tablename__ = "scheduled_task_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("scheduled_tasks.id"), nullable=False)
    status = Column(String(20), nullable=False)  # running / success / failed
    test_run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    error_message = Column(Text)

    __table_args__ = (
        Index("idx_scheduled_task_runs_task_started", "task_id", "started_at"),
    )


# ==================== 能力9：AI 分析结果 ====================


class AIAnalysisResult(Base):
    """AI 分析结果 — 能力9（失败分析/摘要/对比统一落库）"""
    __tablename__ = "ai_analysis_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    analysis_type = Column(SAEnum(AnalysisType, name="analysistype"), nullable=False)
    test_run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=True)
    test_result_id = Column(UUID(as_uuid=True), ForeignKey("test_results.id"), nullable=True)
    input_summary = Column(JSONB, default={})
    analysis_json = Column(JSONB, default={})
    model_used = Column(String(64), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_ai_analysis_project_type_created", "project_id", "analysis_type", "created_at"),
        Index("idx_ai_analysis_test_result", "test_result_id"),
    )


# ==================== 能力12：知识库 RAG ====================

class KnowledgeChunk(Base):
    """知识库切片表 — embedding 用 JSONB 存 float[]，检索在 Python 侧算余弦（不依赖 pgvector）。"""
    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # SAEnum 必须显式 name=，否则 PG 枚举名全小写易触发 asyncpg DatatypeMismatchError
    kb_type = Column(SAEnum(KBChunkType, values_callable=lambda x: [e.value for e in x], name="kbchunktype"), nullable=False, index=True)
    source_ref = Column(String(200), nullable=True, index=True)
    content = Column(Text, nullable=False)
    # JSONB 存 float[]；无嵌入模型时为 NULL（关键词检索兜底）
    embedding = Column(JSONB, nullable=True)
    meta = Column(JSONB, default={})
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_knowledge_chunks_type_created", "kb_type", "created_at"),
    )


class KnowledgeTerm(Base):
    """业务术语表 — 零配置必可用的术语检索来源，重建后纳入 term 类切片。"""
    __tablename__ = "knowledge_terms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term = Column(String(200), nullable=False, index=True)
    aliases = Column(JSONB, default=[])          # list[str]
    technical_meaning = Column(Text, nullable=False)
    domain = Column(String(100), nullable=True, index=True)
    meta = Column(JSONB, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KBRebuildState(Base):
    """知识库重建状态机（单行表，供 API 与 Celery Worker 跨进程共享状态）。"""
    __tablename__ = "kb_rebuild_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    state = Column(String(20), default="idle", nullable=False)  # idle | running | failed
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_rebuild = Column(DateTime, nullable=True)
    last_rebuild_chunks = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)


class KBRuntimeConfig(Base):
    """知识库运行时配置（key-value 风格，供前端开关切换，无需重启）。

    env 仍是兜底默认；前端切换写入此表后，模块级缓存即时失效。
    """
    __tablename__ = "kb_runtime_config"

    key = Column(String(64), primary_key=True)
    value = Column(JSONB, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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

    # 旧库补齐 PG 枚举的小写标签（SAEnum 写 bind 用 member.value；老库 create_all 用 member.name）
    # 涉及枚举：kbchunktype / casesource / caseassetstatus / scenariostatus / endpointsource
    # SAEnum 默认持久化是 PyEnum 成员 NAME（大写），但有些列会按 member.value（小写）写入；
    # 当 PG 枚举仅有大写标签时，写入会抛 "invalid input value for enum xxx: 'yyy'"。
    # 同时插入大写 + 小写标签，兼容两种 bind 方式（002 迁移对 kbchunktype 也用此模式，
    # 但**老库用户 002 迁移未生效时（init_db 启动期 create_all 已建大写枚举）**，这里兜底补小写）。
    _ENUM_CASE_PAIRS: tuple[tuple[str, type[PyEnum]], ...] = (
        ("kbchunktype", KBChunkType),
        ("casesource", CaseSource),
        ("caseassetstatus", CaseAssetStatus),
        ("scenariostatus", ScenarioStatus),
        ("endpointsource", EndpointSource),
    )
    try:
        async with async_engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            for type_name, enum_cls in _ENUM_CASE_PAIRS:
                # 同时建大小写两个 label（兼容大写 NAME 写入 + 小写 VALUE 写入）
                for label in tuple(m.name for m in enum_cls) + tuple(m.value for m in enum_cls):
                    try:
                        await autocommit_conn.execute(
                            text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'")
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to add enum label '{label}' to {type_name}: {e}. "
                            f"若落库报 invalid input value for enum，请执行 `docker compose down -v` 重建数据库。"
                        )
    except Exception as e:
        logger.warning(f"Skip enum case-pair sync (connection error): {e}")
    else:
        logger.info("kbchunktype/casesource/caseassetstatus/scenariostatus/endpointsource enum labels (both case) ensured")

    # 旧库补齐 model_routing 两列（doc_parse_model_id / doc_review_model_id）。
    # 这两列在新增需求中加到 ModelRouting 表，使用 nullable=True 以便老库平滑迁移；
    # create_all 只会建新表、不会 ALTER 已有表，故此处用幂等 ADD COLUMN IF NOT EXISTS 兜底。
    # DDL 不支持参数绑定，列名取自可信字面量，无注入风险。
    try:
        async with async_engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            for col_sql in (
                "ALTER TABLE model_routing ADD COLUMN IF NOT EXISTS doc_parse_model_id VARCHAR(64)",
                "ALTER TABLE model_routing ADD COLUMN IF NOT EXISTS doc_review_model_id VARCHAR(64)",
            ):
                try:
                    await autocommit_conn.execute(text(col_sql))
                except Exception as e:
                    logger.warning(
                        f"Failed to add column ({col_sql}): {e}. "
                        f"请执行 `docker compose down -v` 重建数据库或手动 ALTER。"
                    )
    except Exception as e:
        logger.warning(f"Skip model_routing column sync (connection error): {e}")
    else:
        logger.info("ModelRouting doc_parse/doc_review columns ensured")

    # 旧库补齐 model_routing 的 scenario_orchestration_model_id 列（能力4 新插槽）。
    # 该列使用 nullable=True 以便老库平滑迁移；create_all 不会 ALTER 既有表，
    # 故此处用幂等 ADD COLUMN IF NOT EXISTS 兜底。
    # DDL 不支持参数绑定，列名取自可信字面量，无注入风险。
    try:
        async with async_engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            for col_sql in (
                "ALTER TABLE model_routing ADD COLUMN IF NOT EXISTS scenario_orchestration_model_id VARCHAR(64)",
            ):
                try:
                    await autocommit_conn.execute(text(col_sql))
                except Exception as e:
                    logger.warning(
                        f"Failed to add column ({col_sql}): {e}. "
                        f"请执行 `docker compose down -v` 重建数据库或手动 ALTER。"
                    )
    except Exception as e:
        logger.warning(f"Skip model_routing scenario_orchestration column sync (connection error): {e}")
    else:
        logger.info("ModelRouting scenario_orchestration column ensured")

    # 旧库补齐 doc_reviews.doc_id 的可空性（DROP NOT NULL）。
    # DocReview.doc_id 已改为 nullable=True 以支持独立接口级评审，但 create_all 不会
    # ALTER 既有表，若目标库里 doc_reviews 是由旧定义（doc_id NOT NULL）建出的，
    # 仅改模型不会让既有表结构跟着变，故此处用幂等 DROP NOT NULL 兜底。
    # PostgreSQL 的 ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL 建议在事务外执行，故使用 AUTOCOMMIT；
    # DDL 不支持参数绑定，表名/列名取自可信字面量，无注入风险。
    try:
        async with async_engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            try:
                await autocommit_conn.execute(
                    text("ALTER TABLE doc_reviews ALTER COLUMN doc_id DROP NOT NULL")
                )
            except Exception as e:
                logger.warning(
                    f"Failed to drop NOT NULL on doc_reviews.doc_id: {e}. "
                    f"请执行 `docker compose down -v` 重建数据库或手动 ALTER。"
                )
    except Exception as e:
        logger.warning(f"Skip doc_reviews.doc_id DROP NOT NULL (connection error): {e}")
    else:
        logger.info("DocReview doc_id nullable ensured")

    # 旧库补齐 TestCaseAsset 三列（pre_script / post_script / sql_script — 能力5/6/7）。
    # 这三列使用 nullable=True 以便老库平滑迁移；create_all 不会 ALTER 既有表，
    # 故此处用幂等 ADD COLUMN IF NOT EXISTS 兜底。
    try:
        async with async_engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            for col_sql in (
                "ALTER TABLE test_case_assets ADD COLUMN IF NOT EXISTS pre_script TEXT",
                "ALTER TABLE test_case_assets ADD COLUMN IF NOT EXISTS post_script TEXT",
                "ALTER TABLE test_case_assets ADD COLUMN IF NOT EXISTS sql_script TEXT",
            ):
                try:
                    await autocommit_conn.execute(text(col_sql))
                except Exception as e:
                    logger.warning(
                        f"Failed to add column ({col_sql}): {e}. "
                        f"请执行 `docker compose down -v` 重建数据库或手动 ALTER。"
                    )
    except Exception as e:
        logger.warning(f"Skip test_case_assets script columns sync (connection error): {e}")
    else:
        logger.info("TestCaseAsset pre_script/post_script/sql_script columns ensured")

    # 旧库补齐 model_routing 三列（script_generation_model_id / sql_generation_model_id /
    # report_analysis_model_id — 能力5/6/7/9）。
    # 这三列使用 nullable=True 以便老库平滑迁移；create_all 不会 ALTER 既有表。
    try:
        async with async_engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            for col_sql in (
                "ALTER TABLE model_routing ADD COLUMN IF NOT EXISTS script_generation_model_id VARCHAR(64)",
                "ALTER TABLE model_routing ADD COLUMN IF NOT EXISTS sql_generation_model_id VARCHAR(64)",
                "ALTER TABLE model_routing ADD COLUMN IF NOT EXISTS report_analysis_model_id VARCHAR(64)",
            ):
                try:
                    await autocommit_conn.execute(text(col_sql))
                except Exception as e:
                    logger.warning(
                        f"Failed to add column ({col_sql}): {e}. "
                        f"请执行 `docker compose down -v` 重建数据库或手动 ALTER。"
                    )
    except Exception as e:
        logger.warning(f"Skip model_routing new slot columns sync (connection error): {e}")
    else:
        logger.info("ModelRouting script_generation/sql_generation/report_analysis columns ensured")

    # 能力12：补齐 model_routing.embedding_model_id 列（嵌入模型插槽，nullable=True 老库兼容）。
    # create_all 不会 ALTER 既有表，故此处用幂等 ADD COLUMN IF NOT EXISTS 兜底。
    try:
        async with async_engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            try:
                await autocommit_conn.execute(
                    text("ALTER TABLE model_routing ADD COLUMN IF NOT EXISTS embedding_model_id VARCHAR(64)")
                )
            except Exception as e:
                logger.warning(
                    f"Failed to add column embedding_model_id: {e}. "
                    f"请手动 ALTER 或执行 `docker compose down -v` 重建数据库。"
                )
    except Exception as e:
        logger.warning(f"Skip model_routing embedding_model_id column sync (connection error): {e}")
    else:
        logger.info("ModelRouting embedding_model_id column ensured")

    # 能力12：best-effort 启用 pgvector 快路径（失败仅记日志，代码绝不依赖；
    # 检索使用 JSONB + Python 侧余弦相似度，不要求 pgvector 扩展）。
    try:
        async with async_engine.connect() as conn:
            ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
            try:
                await ac.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception as e:
                logger.info(f"pgvector extension not available (optional, skipped): {e}")
    except Exception as e:
        logger.warning(f"Skip pgvector init: {e}")
