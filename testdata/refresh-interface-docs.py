#!/usr/bin/env python3
"""从运行中的两套被测产品刷新 OpenAPI 文档。"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} 返回 HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def operation_count(document: dict[str, Any]) -> int:
    return sum(
        1
        for path_item in document.get("paths", {}).values()
        for method in path_item
        if method.lower() in METHODS
    )


def save_document(document: dict[str, Any], target: Path, server_url: str, minimum: int) -> None:
    operations = operation_count(document)
    if operations < minimum:
        raise RuntimeError(f"{target.name} 只有 {operations} 个接口操作，拒绝覆盖现有文档")
    document["servers"] = [{"url": server_url, "description": "AITP VM test product"}]
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    print(f"[OK] {target.relative_to(ROOT)}：{operations} 个接口操作")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.125.128", help="被测产品所在主机")
    args = parser.parse_args()

    petclinic = f"http://{args.host}:8301/petclinic"
    ecommerce = f"http://{args.host}:8302"
    try:
        save_document(
            fetch_json(f"{petclinic}/v3/api-docs"),
            ROOT / "spring-petclinic-rest" / "openapi.json",
            petclinic,
            40,
        )
        save_document(
            fetch_json(f"{ecommerce}/swagger.json"),
            ROOT / "restful-ecommerce" / "openapi.json",
            ecommerce,
            10,
        )
    except (OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
