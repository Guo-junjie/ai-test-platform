"""Jenkins 部署完成后触发计划，等待测试与 Java 覆盖率结果；失败则非零退出。"""

import json
import os
import sys
import time
import urllib.error
import urllib.request


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}")
    return value


def request(base: str, path: str, token: str | None = None,
            payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=body, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"平台 API {path} 返回 HTTP {exc.code}: {detail}") from exc


def main() -> None:
    base = required("AITP_URL").rstrip("/")
    plan_id = required("AITP_PLAN_ID")
    commit = required("DEPLOY_COMMIT_SHA")
    login = request(base, "/api/auth/login", payload={
        "username": required("AITP_USER"), "password": required("AITP_PASSWORD")})
    token = login["data"]["token"]
    dispatched = request(base, f"/api/plans/{plan_id}/execute", token,
                         {"commit_sha": commit})
    run_id = dispatched["data"]["test_run_id"]
    print(f"已派发测试任务 {run_id}，部署提交 {commit}", flush=True)

    deadline = time.monotonic() + int(os.environ.get("AITP_TIMEOUT_SECONDS", "1800"))
    while time.monotonic() < deadline:
        run = request(base, f"/api/test-runs/{run_id}", token)["data"]
        if run["status"] in {"completed", "failed", "cancelled"}:
            coverage = request(base, f"/api/coverage/runs/{run_id}", token)["data"]
            print(json.dumps({
                "test_run_id": run_id, "test_status": run["status"],
                "test_error": run.get("error_message"),
                "coverage_status": coverage["status"],
                "coverage_error": coverage.get("error_message"),
                "line_rate": coverage.get("line_rate"),
                "branch_rate": coverage.get("branch_rate"),
                "reports": [item.get("report_id") for item in coverage.get("services", [])],
            }, ensure_ascii=False), flush=True)
            if run["status"] != "completed" or coverage["status"] != "COMPLETED":
                raise RuntimeError("测试或覆盖率门禁未通过")
            return
        time.sleep(5)
    raise RuntimeError(f"等待测试任务 {run_id} 超时")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"CI 验收失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
