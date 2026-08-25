"""
test_requirement_parser.py — 不依赖 Docker/PG/Celery 验证需求解析容错。

策略：直接 exec 模块源文件，跳过 package __init__ 的副作用（避免拉数据库引擎）。
"""
import sys
import importlib.util
from pathlib import Path

BACKEND = Path(r"D:\\code\\WorkbuddyProject\\ai测试自闭环\\ai-test-platform\\backend")
sys.path.insert(0, str(BACKEND))

# 直接 exec 模块源文件，避开 _init_ 的数据库 engine 副作用
spec = importlib.util.spec_from_file_location(
    "req_parser_test",
    BACKEND / "app" / "modules" / "doc_parser" / "requirement_parser.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
_coerce_item = mod._coerce_item
_looks_like_requirement_doc = mod._looks_like_requirement_doc
_regex_fallback = mod._regex_fallback


# ============ Test 1: 标准 dict ============

def test_dict_item_basic():
    item = {
        "rid": "FR-USER-01",
        "title": "用户注册",
        "description": "手机号+密码注册",
        "priority": "P0",
        "category": "functional",
        "acceptance_criteria": ["合法手机号 → 201", "非法手机号 → 400"],
        "test_points": ["正常", "异常"],
    }
    spec = _coerce_item(item, 0)
    assert spec.rid == "FR-USER-01"
    assert spec.title == "用户注册"
    assert spec.priority == "P0"
    assert spec.category == "functional"
    assert len(spec.acceptance_criteria) == 2
    assert spec.confidence == 0.8
    print("✅ T1 dict 路径 OK")


# ============ Test 2: list of str 容错（关键修复） ============

def test_str_item_extracts_rid():
    item = "FR-USER-01 用户注册：手机号+密码"
    spec = _coerce_item(item, 5)
    assert spec.rid in ("FR-USER-01",), f"unexpected rid: {spec.rid!r}"
    assert "用户注册" in spec.title
    assert spec.confidence < 0.5  # str 路径低置信度
    print(f"✅ T2a str → rid='{spec.rid}' title='{spec.title}'")

def test_str_item_no_prefix():
    spec = _coerce_item("支持手机号+密码注册，11位 1[3-9]开头", 1)
    # 无 rid 前缀，应自动生成 REQ-NNN
    assert spec.rid == "REQ-001", f"rid={spec.rid!r}"
    assert "支持手机号" in spec.title
    print(f"✅ T2b str no-prefix → rid='REQ-001' title='{spec.title[:30]}...'")

def test_str_item_empty_raises():
    try:
        _coerce_item("   ", 0)
        raise AssertionError("应抛 ValueError")
    except ValueError:
        print("✅ T2c 空字符串抛 ValueError")


# ============ Test 3: looks_like_requirement_doc ============

PIP_FILE = """fastapi==0.110.0
uvicorn==0.27.1
pydantic==2.6.1
pyjwt==2.8.0
python-multipart==0.0.9
"""

REQUIREMENT_DOC = """# 电商订单中心——需求说明书 v1.2

## 1. 背景与目标

## 3. 功能性需求

FR-USER-01: 手机号+密码注册：手机号格式校验（11 位 1[3-9]开头）、密码强度（≥8 位含大小写数字特殊符号）。
FR-USER-02: 账号密码登录：5 次错误锁定 30 分钟，登录成功返回 JWT 双 Token。
FR-USER-03: Refresh Token 刷新 Access Token；Refresh 过期需重新登录。
FR-PRODUCT-01: 商品列表：支持关键词、分类、价格区间、排序、分页；仅展示已上架。
FR-PRODUCT-02: 商品详情：返回 SPU + SKU 列表 + 库存 + 评价数；下架商品 404。
FR-ORDER-01: 创建订单：根据 SKU + 数量 + 地址，调用库存预占，返回订单号。
FR-ORDER-02: 订单支付：必须传幂等键，相同 key 5 分钟内幂等。
FR-ORDER-03: 订单取消：PENDING 或 PAID 可取消。
NFR-1: 性能：登录 P99 < 200ms，下单 P99 < 300ms。
NFR-2: 安全：全站 HTTPS，bcrypt 密码加密。
"""


def test_pip_style_rejected():
    assert _looks_like_requirement_doc(PIP_FILE) is False
    print("✅ T3a pip 依赖文件被拒绝")

def test_real_requirement_doc_accepted():
    assert _looks_like_requirement_doc(REQUIREMENT_DOC) is True
    print("✅ T3b 标准需求文档被接受")

def test_short_text_rejected():
    assert _looks_like_requirement_doc("a") is False
    assert _looks_like_requirement_doc("login\nregister") is False
    print("✅ T3c 短文本被拒绝")


# ============ Test 4: regex_fallback ============

def test_pip_fallback_zero():
    items = _regex_fallback(PIP_FILE)
    assert items == [], f"got {len(items)} items from pip file"
    print("✅ T4a pip 文件 → regex fallback 0 条（不再误生成骨架）")

def test_real_doc_fallback_extracted():
    items = _regex_fallback(REQUIREMENT_DOC)
    # FR-USER-01/02/03 应该被抽到
    rids = [it.rid for it in items]
    assert any("FR-USER" in r for r in rids), f"rids={rids!r}"
    print(f"✅ T4b 标准需求文档 → 抽到 {len(items)} 条（含 {rids}）")


if __name__ == "__main__":
    print("=" * 60)
    test_dict_item_basic()
    test_str_item_extracts_rid()
    test_str_item_no_prefix()
    test_str_item_empty_raises()
    test_pip_style_rejected()
    test_real_requirement_doc_accepted()
    test_short_text_rejected()
    test_pip_fallback_zero()
    test_real_doc_fallback_extracted()
    print()
    print("🎉 requirement_parser 全场景通过")
