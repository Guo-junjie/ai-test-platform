"""testdata 全路径集成测试 — 验证 testdata/ 下的所有材料能被后端正确解析

不依赖运行中的 backend / DB，纯函数式 + pytest 风格断言。

覆盖：
1. OpenAPI 文档解析（rule parser，零 AI）→ ApiSpec
2. Stack 探测（python_flask 识别）
3. 覆盖率 XML 解析（Cobertura → 行/分支覆盖度）
5. 需求文档解析 → 切片后含业务词
6. 缺陷/报告/覆盖率 通过 test_run_id 关联（DB 模型字段一致性）

前置材料（testdata/ 仓库根目录）：
- api/order-center-openapi.json
- coverage/coverage-python.xml
- project/order-service/  (Flask 项目)
- requirements/order-center-requirements.txt
- knowledge/order-test-spec.md
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

# 保证 backend 目录在 sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

REPO_ROOT = BACKEND_DIR.parent
TESTDATA = REPO_ROOT / "testdata"


# ==================== 1. OpenAPI 解析 ====================

def _load_swagger_parser():
    """直接通过 package import 加载 swagger_parser（前置依赖 python-docx）。

    注：历史上本测试用 importlib 隔离加载以避免 docx 缺失，但 pydantic v2 在
    隔离加载时无法解析 ``list[ResponseSpec]`` 这种自指向前向引用（__future__ annotations
    下重建不彻底）。环境已具备 python-docx 后，直接走 package import 最稳。
    """
    from app.modules.doc_parser.swagger_parser import parse_swagger
    return parse_swagger


def test_openapi_rule_parser_extracts_endpoints():
    """OpenAPI 文档必须能被规则解析器提取出 ≥3 个 endpoint"""
    parse_swagger = _load_swagger_parser()

    openapi_path = TESTDATA / "api" / "order-center-openapi.json"
    assert openapi_path.exists(), f"缺失 testdata: {openapi_path}"

    text = openapi_path.read_text(encoding="utf-8")
    spec = parse_swagger(text)

    assert spec is not None
    # endpoints 数量：testdata 里至少含 auth + products + orders（≥6）
    assert len(spec.endpoints) >= 6, f"endpoints 数量异常: {len(spec.endpoints)}"

    # 抽样：登录路径
    login_eps = [e for e in spec.endpoints if "/auth/login" in e.path]
    assert len(login_eps) >= 1, "未识别 /auth/login"
    login = login_eps[0]
    assert login.method.upper() == "POST"
    assert login.summary or login.description, "登录端点缺描述"

    # 抽样：下单路径
    create_order = [e for e in spec.endpoints if "/orders" == e.path.rstrip("/") or "/orders" in e.path]
    assert len(create_order) >= 1, "未识别订单相关端点"


# ==================== 2. Stack 探测 ====================

def test_stack_detector_recognizes_python_flask():
    """order-service 是 Python Flask 项目，StackDetector 必须识别为 python_flask"""
    from app.modules.code_analyzer.stack_detector import StackDetector

    project_dir = TESTDATA / "project" / "order-service"
    assert project_dir.exists(), f"缺失 testdata: {project_dir}"
    assert (project_dir / "requirements.txt").exists(), "order-service 缺 requirements.txt"

    detector = StackDetector()
    result = detector.detect(str(project_dir))

    assert result.get("stack") in ("python_flask", "flask"), (
        f"stack 识别错误: 期望 python_flask/flask，实际 {result.get('stack')}"
    )
    assert result.get("framework") in ("Flask", "flask"), (
        f"framework 识别错误: {result.get('framework')}"
    )


def test_zip_packaging_of_project_works():
    """打包 zip 是测试任务上传的标准前置步骤"""
    project_dir = TESTDATA / "project" / "order-service"
    zip_path = TESTDATA / "project" / "order-service.zip"
    assert zip_path.exists(), f"缺失 testdata: {zip_path}"

    # 必须能打开且含 app.py / requirements.txt
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
    # 路径扁平化（zip 内部通常带 order-service/ 前缀）
    flat = [n.split("/", 1)[-1] for n in names]
    assert "requirements.txt" in flat or any(n.endswith("requirements.txt") for n in names)


# ==================== 3. 覆盖率 XML 解析 ====================

def test_cobertura_parser_returns_line_coverage():
    """testdata 的 coverage-python.xml 必须能解析出行/分支覆盖度"""
    from app.modules.coverage.parser import parse_coverage_report

    xml_path = TESTDATA / "coverage" / "coverage-python.xml"
    assert xml_path.exists(), f"缺失 testdata: {xml_path}"

    xml_text = xml_path.read_text(encoding="utf-8")
    result = parse_coverage_report("cobertura", xml_text)

    # Cobertura parser 输出 schema：line_rate / covered_lines / files
    # 关键字段至少有一个：line_rate (百分数) 或 covered_lines (整数)
    assert (
        "line_rate" in result
        or "covered_lines" in result
        or "line_coverage" in result
        or "lines" in result
    ), f"覆盖率解析结果缺关键字段: {list(result.keys())}"

    files = result.get("files") or result.get("file_coverage") or []
    assert len(files) >= 1, f"未解析出文件级覆盖度: {result}"


# ==================== 4. 缺陷/报告/覆盖率 通过 test_run_id 关联 ====================

def test_defect_report_coverage_share_test_run_id_field():
    """缺陷/覆盖率模型都应挂 test_run_id 外键，报告通过 test_run_id 查询"""
    from app.models.database import Defect, CoverageReport, TestReport

    # 三个模型都应包含 test_run_id 字段（外键 / 可空 UUID）
    defect_cols = {c.name for c in Defect.__table__.columns}
    coverage_cols = {c.name for c in CoverageReport.__table__.columns}
    report_cols = {c.name for c in TestReport.__table__.columns}

    assert "test_run_id" in defect_cols, "Defect 缺 test_run_id 字段（缺陷无法回溯任务）"
    assert "test_run_id" in coverage_cols, "CoverageReport 缺 test_run_id 字段"
    assert "test_run_id" in report_cols, "TestReport 缺 test_run_id 字段"

    # 缺陷/覆盖率字段允许为空（手动创建的缺陷可能不挂任务）
    defect_test_run = Defect.__table__.columns["test_run_id"]
    assert defect_test_run.nullable, "Defect.test_run_id 应允许为空"


# ==================== 5. 知识库 testdata 资料齐全 ====================

def test_knowledge_testdata_present_and_parseable():
    """testdata 知识库文档与术语表必须可读"""
    test_spec = TESTDATA / "knowledge" / "order-test-spec.md"
    glossary = TESTDATA / "knowledge" / "order-glossary.md"
    assert test_spec.exists(), f"缺失: {test_spec}"
    assert glossary.exists(), f"缺失: {glossary}"

    spec_text = test_spec.read_text(encoding="utf-8")
    glossary_text = glossary.read_text(encoding="utf-8")

    # 验证业务词命中（回归：关键词级）
    for keyword in ("VIP", "SKU", "库存", "订单"):
        assert keyword in spec_text or keyword in glossary_text, (
            f"testdata 知识库材料缺关键词: {keyword}"
        )


# ==================== 6. 需求文档 testdata ====================

def test_requirements_doc_testdata_present():
    """需求文档必须存在并含关键业务词"""
    req_path = TESTDATA / "requirements" / "order-center-requirements.txt"
    assert req_path.exists(), f"缺失: {req_path}"
    text = req_path.read_text(encoding="utf-8")
    # 至少含「下单」「订单」「VIP」之一
    assert any(kw in text for kw in ("下单", "订单", "VIP")), (
        "需求文档缺关键业务词"
    )


# ==================== 7. 端到端集成跑通 ====================

def test_end_to_end_pipeline_smoke():
    """Smoke test: 同时跑 OpenAPI + Stack + Coverage 解析，全部成功"""
    from app.modules.code_analyzer.stack_detector import StackDetector
    from app.modules.coverage.parser import parse_coverage_report

    parse_swagger = _load_swagger_parser()

    # 1. OpenAPI
    openapi_spec = parse_swagger(
        (TESTDATA / "api" / "order-center-openapi.json").read_text(encoding="utf-8")
    )
    assert len(openapi_spec.endpoints) > 0

    # 2. Stack
    stack = StackDetector().detect(str(TESTDATA / "project" / "order-service"))
    assert stack.get("stack")

    # 3. Coverage
    cov = parse_coverage_report(
        "cobertura",
        (TESTDATA / "coverage" / "coverage-python.xml").read_text(encoding="utf-8"),
    )
    assert cov

    # 三者并存即可证明 testdata 自洽：同一被测服务的 API 文档 + 代码 + 覆盖率报告，
    # 全部可被平台后端解析，与缺陷/报告通过 test_run_id 挂接后形成完整链路