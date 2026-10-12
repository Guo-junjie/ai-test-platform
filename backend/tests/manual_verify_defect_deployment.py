"""已部署服务只读验收；可生成 15 分钟浏览器会话文件，不在日志输出令牌。"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import httpx
from sqlalchemy import select, text
from app.models import database as m
from app.modules.auth.auth_service import AuthService
from app.utils.database import AsyncSessionLocal


async def verify(session_path):
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "019"
        admin = (await db.execute(select(m.User).where(m.User.is_active.is_(True), m.User.role.in_([m.UserRole.SUPER_ADMIN, m.UserRole.ADMIN])).limit(1))).scalar_one()
        token = AuthService.create_access_token(str(admin.id), admin.username, admin.role.value, expires_hours=0.25)
        user = {"id": str(admin.id), "username": admin.username, "role": admin.role.value, "is_active": True}
        counts = {model.__tablename__: (await db.execute(select(text("count(*)")).select_from(model))).scalar_one() for model in (m.AIModelConfig, m.ModelRouting, m.User, m.Project, m.Defect)}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", headers={"Authorization": "Bearer " + token}, trust_env=False, timeout=15) as client:
        health = await client.get("/api/health"); assert health.status_code == 200
        listing = await client.get("/api/defects"); assert listing.status_code == 200, listing.text
        assert "stats" in listing.json()["data"]
        schema = (await client.get("/openapi.json")).json()["paths"]
        for route in ("/api/defects/metadata", "/api/defects/{defect_id}/transitions", "/api/defects/{defect_id}/events", "/api/projects/{project_id}/modules"):
            assert route in schema, route
        projects = (await client.get("/api/projects")).json()["data"].get("list", [])
        if projects:
            options = await client.get("/api/defects/metadata", params={"project_id": projects[0]["id"]})
            assert options.status_code == 200 and len(options.json()["data"]["states"]) == 8
    if session_path:
        path = Path(session_path)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({"token": token, "user": user}, output)
        os.chmod(path, 0o600)
    print("PASS：部署库为 019，健康、缺陷列表、新路由和已有项目选项可用。")
    print("记录数（不含密钥）：" + json.dumps(counts))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-session", help="可选私有临时文件，用于浏览器只读验收")
    asyncio.run(verify(parser.parse_args().browser_session))
