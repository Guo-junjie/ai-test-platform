"""在真实 PostgreSQL 事务中验证人工用例链路，结束时回滚全部验收数据。

运行：docker exec -w /app aitp-backend python tests/manual_verify_manual_case.py
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.database import DocFormat, Project, RequirementDoc, SourceType, User, UserRole
from app.modules.auth.auth_service import AuthService
from app.utils.database import async_engine, get_db_session


async def verify():
    async_engine.echo = False
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as db:
            try:
                actor = (await db.execute(select(User).where(
                    User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN]), User.is_active.is_(True),
                ).limit(1))).scalar_one()
                project = Project(id=uuid4(), name="人工用例事务验收", owner_id=actor.id,
                                  source_type=SourceType.UPLOAD)
                db.add(project)
                await db.flush()
                document = RequirementDoc(id=uuid4(), project_id=project.id, filename="人工用例验收需求.md",
                                          format=DocFormat.TXT, storage_key="transaction-only")
                db.add(document)
                await db.flush()

                async def isolated_db():
                    yield db

                app.dependency_overrides[get_db_session] = isolated_db
                token = AuthService.create_access_token(str(actor.id), actor.username, actor.role.value)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                             headers={"Authorization": f"Bearer {token}"}) as client:
                    payload = {
                        "project_id": str(project.id), "title": "人工用例事务验收", "folder": "订单",
                        "preconditions": "用户已登录", "steps": ["进入购物车", "提交订单"],
                        "expected_result": "订单创建成功", "priority": "P1", "tags": ["回归"],
                        "requirement_doc_id": str(document.id), "requirement_ref": "REQ-MANUAL-01",
                    }
                    created = await client.post("/api/cases", json=payload)
                    assert created.status_code == 200, created.text
                    asset = created.json()["data"]
                    assert asset["review_state"] == "draft" and asset["source"] == "manual"
                    duplicate = await client.post("/api/cases", json=payload)
                    assert duplicate.status_code == 409, duplicate.text
                    listing = await client.get("/api/cases", params={"project_id": str(project.id)})
                    assert listing.status_code == 200 and listing.json()["data"]["total"] == 1, listing.text
                    options = await client.get("/api/cases/manual/options", params={"project_id": str(project.id)})
                    assert options.status_code == 200 and options.json()["data"]["tags"] == ["回归"], options.text
                    versions = await client.get(f'/api/cases/{asset["id"]}/versions')
                    assert versions.status_code == 200 and versions.json()["data"]["items"][0]["version"] == 1, versions.text
                    trace = await client.get(f'/api/cases/{asset["id"]}/traceability')
                    assert trace.status_code == 200 and trace.json()["data"]["source"]["requirement"]["id"] == str(document.id), trace.text
                    review = await client.post(f'/api/cases/{asset["id"]}/submit-review')
                    assert review.status_code == 200, review.text
                print("PASS PostgreSQL + real auth: create, duplicate warning, list, options, version, requirement trace, submit review")
            finally:
                app.dependency_overrides.pop(get_db_session, None)
                await transaction.rollback()
                print("ROLLBACK all acceptance data")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(verify())
