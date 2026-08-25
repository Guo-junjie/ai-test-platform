"""一键验证 4 个解析/评审/分析功能的 E2E 脚本（部署机直接跑）。

覆盖：
  ① 接口文档解析   POST /api/docs/upload + POST /api/docs/{id}/parse
  ② 接口文档评审   POST /api/docs/reviews
  ③ 需求文档解析   POST /api/requirements
  ④ 代码解析       POST /api/analysis/run
  ⑤ （可选）需求生成用例  POST /api/requirements/{id}/generate-cases

用法：
  docker compose exec backend python -m scripts.verify_parse_pipeline
      --code-path /tmp/code-sample
  或者本地：
  python -m scripts.verify_parse_pipeline --base http://localhost:8000

参数：
  --base           API base URL（默认 http://localhost:8000）
  --code-path      代码工程绝对路径（默认 /tmp/code-sample，需含 main.py）
  --no-ai          不调 AI（速度更快、纯结构化）
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

import requests

DEFAULT_USERNAME = "superadmin"
DEFAULT_PASSWORD = "SuperAdmin123!"


def _hr(t: str) -> None:
    print()
    print("=" * 70)
    print(f" {t}")
    print("=" * 70)


def _login(base: str, session: requests.Session) -> str:
    _hr(f"[1/6] 登录 {DEFAULT_USERNAME}")
    r = session.post(
        f"{base}/api/auth/login",
        json={"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["data"]["access_token"]
    print(f"  ✅ 登录成功，token len={len(token)}")
    return token


def _get_demo_project(base: str, session: requests.Session, headers: dict) -> str:
    _hr("[2/6] 取 e2e-demo-project UUID")
    r = session.get(f"{base}/api/projects", headers=headers, timeout=30)
    r.raise_for_status()
    rows = r.json()["data"]
    hit = next((p for p in rows if p.get("name") == "e2e-demo-project"), None)
    if not hit:
        raise SystemExit(
            f"找不到 e2e-demo-project；当前项目列表={[p['name'] for p in rows]}。\n"
            f"请先跑 python -m scripts.seed_e2e"
        )
    pid = hit["id"]
    print(f"  ✅ e2e-demo-project UUID = {pid}")
    return pid


def _upload_doc(
    base: str,
    session: requests.Session,
    headers: dict,
    project_id: str,
    file_path: Path,
    doc_type: str,
) -> str:
    _hr(f"[3/6] 上传接口文档（{file_path.name}）")
    with open(file_path, "rb") as f:
        r = session.post(
            f"{base}/api/docs/upload",
            headers=headers,
            data={"project_id": project_id, "doc_type": doc_type},
            files={"file": (file_path.name, f, "application/json")},
            timeout=60,
        )
    r.raise_for_status()
    doc_id = r.json()["data"]["doc_id"]
    sha = r.json()["data"]["sha256"]
    print(f"  ✅ doc_id = {doc_id}（sha256={sha[:12]}...）")
    return doc_id


def _parse_doc(
    base: str,
    session: requests.Session,
    headers: dict,
    doc_id: str,
) -> dict:
    _hr("[3.5/6] 解析接口文档（POST /api/docs/{id}/parse）")
    r = session.post(
        f"{base}/api/docs/{doc_id}/parse",
        headers=headers,
        json={"use_ai": True, "max_endpoints": 50},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()["data"]
    eps = data.get("endpoints") or []
    print(
        f"  ✅ 解析完成：engine={data.get('parse_engine')}, "
        f"endpoints={data.get('endpoint_count', len(eps))}, "
        f"degraded={data.get('degraded')}"
    )
    if eps:
        first = eps[0]
        print(f"  示例  endpoint: {first.get('method')} {first.get('path')}")
    return data


def _review_doc(
    base: str,
    session: requests.Session,
    headers: dict,
    project_id: str,
    doc_id: str,
) -> dict:
    _hr("[4/6] AI 评审该接口文档（POST /api/docs/reviews）")
    r = session.post(
        f"{base}/api/docs/reviews",
        headers=headers,
        json={"project_id": project_id, "doc_id": doc_id},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()["data"]
    score = data.get("overall_score") or data.get("score")
    issues = data.get("issues") or []
    print(f"  ✅ 评审完成：overall_score={score}（{len(issues)} 条建议）")
    for i, iss in enumerate(issues[:3], 1):
        title = iss.get("title") if isinstance(iss, dict) else str(iss)
        print(f"     {i}. {title}")
    return data


def _upload_requirement(
    base: str,
    session: requests.Session,
    headers: dict,
    project_id: str,
    file_path: Path,
) -> str:
    _hr(f"[5/6] 上传需求文档（{file_path.name}）")
    with open(file_path, "rb") as f:
        r = session.post(
            f"{base}/api/requirements",
            headers=headers,
            data={"project_id": project_id, "use_ai": "true"},
            files={"file": (file_path.name, f, "text/markdown")},
            timeout=180,
        )
    r.raise_for_status()
    data = r.json()["data"]
    req_id = data["id"]
    total = data.get("total", 0)
    print(
        f"  ✅ 需求文档解析完成：id={req_id}, "
        f"parse_engine={data.get('parse_engine')}, "
        f"需求数={total}"
    )
    return req_id


def _gen_cases_for_requirement(
    base: str,
    session: requests.Session,
    headers: dict,
    req_id: str,
) -> None:
    _hr(f"[5.5/6] 基于需求生成测试用例（{req_id}）")
    try:
        r = session.post(
            f"{base}/api/requirements/{req_id}/generate-cases",
            headers=headers,
            json={"count": 5},
            timeout=300,
        )
        r.raise_for_status()
        cnt = (r.json().get("data") or {}).get("count")
        print(f"  ✅ 基于需求生成用例：{cnt} 条")
    except requests.HTTPError as e:
        print(f"  ⚠️  生成用例失败（可忽略）: {e.response.status_code} {e.response.text[:200]}")


def _analyze_code(
    base: str,
    session: requests.Session,
    headers: dict,
    code_path: str,
) -> None:
    _hr(f"[6/6] 代码解析（local_path={code_path}）")
    r = session.post(
        f"{base}/api/analysis/run",
        headers=headers,
        json={"local_path": code_path},
        timeout=300,
    )
    if not r.ok:
        print(f"  ⚠️  {r.status_code} {r.text[:300]}")
        return
    data = r.json()["data"]
    stack = data.get("tech_stack") or {}
    apis = data.get("apis") or []
    ai = data.get("ai_analysis") or {}
    print(
        f"  ✅ 识别栈={stack.get('stack')}（{stack.get('language')}+{stack.get('framework')}）"
    )
    print(f"     提取 API={len(apis)} 条；业务模块={len(ai.get('business_modules') or [])}；风险点={len(ai.get('risk_areas') or [])}")
    for api in apis[:3]:
        print(f"       {api.get('method', '?')} {api.get('path', '?')}  {api.get('summary', '')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--code-path", default="/tmp/code-sample")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    code_sample = Path("/workspace/demo-materials/code-sample")
    openapi = Path("/workspace/demo-materials/openapi.json")
    requirement = Path("/workspace/demo-materials/requirement.md")

    # 相对容器外兜底
    if not openapi.exists():
        openapi = Path("/tmp/openapi.json")
    if not requirement.exists():
        requirement = Path("/tmp/requirement.md")
    if not code_sample.exists():
        code_sample_local = Path(args.code_path)
        if code_sample_local.exists():
            code_sample = code_sample_local

    s = requests.Session()
    token = _login(base, s)
    headers = {"Authorization": f"Bearer {token}"}

    pid = _get_demo_project(base, s, headers)
    if not openapi.exists():
        print(f"⚠️  找不到 openapi.json（{openapi}），跳过接口文档/评审两块")
    else:
        doc_id = _upload_doc(base, s, headers, pid, openapi, doc_type="openapi")
        _parse_doc(base, s, headers, doc_id)
        _review_doc(base, s, headers, pid, doc_id)

    if not requirement.exists():
        print(f"⚠️  找不到 requirement.md（{requirement}），跳过需求文档")
    else:
        req_id = _upload_requirement(base, s, headers, pid, requirement)
        _gen_cases_for_requirement(base, s, headers, req_id)

    if not code_sample.exists():
        print(f"⚠️  找不到代码工程（{code_sample}），跳过代码解析")
    else:
        _analyze_code(base, s, headers, str(code_sample))

    print()
    print("🎉 全流程跑完；若任何段显示 ⚠️ 请贴对应日志回来排查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
