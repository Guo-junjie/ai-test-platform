"""验证 testdata 中两套长期被测产品的数据包完整且可被平台解析。

本测试不依赖运行中的服务或数据库。在线连通性由 testdata/smoke-test.py 验证。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

REPO_ROOT = BACKEND_DIR.parent
TESTDATA = REPO_ROOT / "testdata"
PRODUCTS = {
    "spring-petclinic-rest": {
        "minimum_operations": 40,
        "required_paths": {"/api/owners", "/api/pets", "/api/visits"},
        "server_suffix": ":8301/petclinic",
        "requirements_keywords": {"主人", "宠物", "就诊"},
    },
    "restful-ecommerce": {
        "minimum_operations": 10,
        "required_paths": {"/auth", "/addOrder", "/getAllOrders"},
        "server_suffix": ":8302",
        "requirements_keywords": {"订单", "认证", "令牌"},
    },
}


def _load_swagger_parser():
    from app.modules.doc_parser.swagger_parser import parse_swagger

    return parse_swagger


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _operation_count(document: dict) -> int:
    methods = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    return sum(
        1
        for path_item in document.get("paths", {}).values()
        for method in path_item
        if method.lower() in methods
    )


def test_testdata_only_contains_two_product_directories():
    """旧订单样例、覆盖率样例和历史执行产物不应再次混入数据包。"""
    directories = {path.name for path in TESTDATA.iterdir() if path.is_dir()}
    assert directories == set(PRODUCTS)


@pytest.mark.parametrize("product_name", PRODUCTS)
def test_openapi_documents_are_complete_and_parseable(product_name: str):
    config = PRODUCTS[product_name]
    openapi_path = TESTDATA / product_name / "openapi.json"
    document = _load_json(openapi_path)

    assert document.get("openapi") or document.get("swagger")
    assert config["required_paths"].issubset(document.get("paths", {}))
    assert _operation_count(document) >= config["minimum_operations"]
    assert document["servers"][0]["url"].endswith(config["server_suffix"])

    spec = _load_swagger_parser()(openapi_path.read_text(encoding="utf-8"))
    assert spec is not None
    assert len(spec.endpoints) >= config["minimum_operations"]


@pytest.mark.parametrize("product_name", PRODUCTS)
def test_product_documents_cover_platform_workflow(product_name: str):
    """每个产品必须具备需求解析、知识库和人工使用所需文档。"""
    product_dir = TESTDATA / product_name
    for filename in ("README.md", "requirements.md", "test-spec.md", "glossary.md"):
        path = product_dir / filename
        assert path.exists(), f"缺少 {path}"
        assert len(path.read_text(encoding="utf-8")) >= 200, f"{path} 内容过少"

    requirements = (product_dir / "requirements.md").read_text(encoding="utf-8")
    for keyword in PRODUCTS[product_name]["requirements_keywords"]:
        assert keyword in requirements

    readme = (product_dir / "README.md").read_text(encoding="utf-8")
    for keyword in ("被测服务 URL", "OpenAPI", "推荐测试流程", "建议用例"):
        assert keyword in readme


def test_request_examples_are_valid_and_match_openapi_contracts():
    owner = _load_json(TESTDATA / "spring-petclinic-rest" / "requests" / "create-owner.json")
    assert {"firstName", "lastName", "address", "city", "telephone"}.issubset(owner)

    auth = _load_json(TESTDATA / "restful-ecommerce" / "requests" / "auth.json")
    assert auth == {"username": "admin", "password": "secretPass123"}

    orders = _load_json(TESTDATA / "restful-ecommerce" / "requests" / "add-order.json")
    assert isinstance(orders, list) and len(orders) == 1
    required = {"user_id", "product_id", "product_name", "product_amount", "qty", "tax_amt", "total_amt"}
    assert required.issubset(orders[0])


def test_compose_defines_reproducible_long_running_services():
    compose_text = (TESTDATA / "compose.yml").read_text(encoding="utf-8")
    for expected in (
        "springcommunity/spring-petclinic-rest@sha256:",
        "mfaisalkhatri/restful-ecommerce-app@sha256:",
        '"8301:9966"',
        '"8302:3004"',
        "restart: unless-stopped",
    ):
        assert expected in compose_text
    assert compose_text.count("restart: unless-stopped") == 2


@pytest.mark.parametrize("script_name", ["smoke-test.py", "refresh-interface-docs.py"])
def test_maintenance_scripts_have_valid_syntax(script_name: str):
    source = (TESTDATA / script_name).read_text(encoding="utf-8")
    ast.parse(source, filename=script_name)


def test_defect_report_coverage_share_test_run_id_field():
    """缺陷、报告和覆盖率数据应能回溯同一次测试运行。"""
    from app.models.database import CoverageReport, Defect, TestReport

    defect_cols = {column.name for column in Defect.__table__.columns}
    coverage_cols = {column.name for column in CoverageReport.__table__.columns}
    report_cols = {column.name for column in TestReport.__table__.columns}

    assert "test_run_id" in defect_cols
    assert "test_run_id" in coverage_cols
    assert "test_run_id" in report_cols
    assert Defect.__table__.columns["test_run_id"].nullable


def test_all_product_openapi_documents_parse_in_one_run():
    """模拟用户连续导入两套产品接口文档。"""
    parse_swagger = _load_swagger_parser()
    parsed = {
        name: parse_swagger((TESTDATA / name / "openapi.json").read_text(encoding="utf-8"))
        for name in PRODUCTS
    }
    assert all(spec.endpoints for spec in parsed.values())
    assert len(parsed["spring-petclinic-rest"].endpoints) > len(parsed["restful-ecommerce"].endpoints)
