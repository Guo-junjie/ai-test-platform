#!/usr/bin/env python3
"""验证两套被测产品与仓库内 OpenAPI 数据是否可用。"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def request_json(url: str, *, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body)


def count_operations(document: dict[str, Any]) -> int:
    methods = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    return sum(
        1
        for path_item in document.get("paths", {}).values()
        for method in path_item
        if method.lower() in methods
    )


def check_document(path: Path, minimum_operations: int) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    operations = count_operations(document)
    if operations < minimum_operations:
        raise AssertionError(f"{path} 只有 {operations} 个操作，预期至少 {minimum_operations} 个")
    print(f"[OK] {path.relative_to(ROOT)}：{operations} 个接口操作")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.125.128", help="被测产品所在主机")
    args = parser.parse_args()

    try:
        petclinic = f"http://{args.host}:8301/petclinic"
        status, body = request_json(f"{petclinic}/actuator/health")
        assert status == 200 and body.get("status") == "UP", body
        status, owners = request_json(f"{petclinic}/api/owners")
        assert status == 200 and isinstance(owners, list), owners
        print(f"[OK] Spring PetClinic REST：健康，主人数据 {len(owners)} 条")

        ecommerce = f"http://{args.host}:8302"
        status, health = request_json(f"{ecommerce}/health")
        assert status == 200, health
        status, auth = request_json(
            f"{ecommerce}/auth",
            payload={"username": "admin", "password": "secretPass123"},
        )
        assert status == 201 and auth.get("token"), auth
        print("[OK] RESTful E-Commerce：健康，认证成功")

        check_document(ROOT / "spring-petclinic-rest" / "openapi.json", 40)
        check_document(ROOT / "restful-ecommerce" / "openapi.json", 10)
    except (AssertionError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print("两套被测产品及接口文档验证通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
