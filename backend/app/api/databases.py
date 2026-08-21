"""
能力7（数据库连接管理）API 路由

提供：
- GET  /:          列表
- POST /:          创建（密码加密存储）
- GET  /{id}:      详情（密码脱敏返回）
- PUT  /{id}:      更新
- DELETE /{id}:    删除
- GET  /{id}/schema: 获取表结构
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.database_conn import (
    DatabaseConnectionRequest,
    DatabaseConnectionUpdate,
    DatabaseConnectionResponse,
)
from app.utils.crypto import encrypt
from app.utils.database import get_db_session

router = APIRouter()


@router.get("")
async def list_databases(
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取数据库连接列表。"""
    from app.models.database import DatabaseConnection

    query = select(DatabaseConnection).order_by(DatabaseConnection.created_at.desc())
    if project_id:
        query = query.where(DatabaseConnection.project_id == project_id)

    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "code": 0,
        "data": {
            "items": [
                {
                    "id": str(item.id),
                    "name": item.name,
                    "db_type": item.db_type,
                    "host": item.host,
                    "port": item.port,
                    "username": item.username,
                    "password": "****",
                    "database": item.database,
                    "project_id": str(item.project_id) if item.project_id else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                }
                for item in items
            ],
            "total": len(items),
        },
        "message": "ok",
    }


@router.post("")
async def create_database(
    req: DatabaseConnectionRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """创建数据库连接（密码加密存储）。"""
    from app.models.database import DatabaseConnection

    encrypted_password = encrypt(req.password) if req.password else ""

    conn = DatabaseConnection(
        id=uuid.uuid4(),
        project_id=uuid.UUID(req.project_id) if req.project_id else None,
        name=req.name,
        db_type=req.db_type,
        host=req.host,
        port=req.port,
        database=req.database,
        username=req.username,
        password_encrypted=encrypted_password,
    )
    db.add(conn)
    await db.flush()
    await db.refresh(conn)

    return {
        "code": 0,
        "data": {
            "id": str(conn.id),
            "name": conn.name,
            "db_type": conn.db_type,
            "host": conn.host,
            "port": conn.port,
            "username": conn.username,
            "password": "****",
            "database": conn.database,
            "project_id": str(conn.project_id) if conn.project_id else None,
            "created_at": conn.created_at.isoformat() if conn.created_at else None,
            "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
        },
        "message": "ok",
    }


@router.get("/{conn_id}")
async def get_database(
    conn_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取数据库连接详情（密码脱敏）。"""
    from app.models.database import DatabaseConnection

    result = await db.execute(
        select(DatabaseConnection).where(DatabaseConnection.id == conn_id)
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Database connection not found")

    return {
        "code": 0,
        "data": {
            "id": str(conn.id),
            "name": conn.name,
            "db_type": conn.db_type,
            "host": conn.host,
            "port": conn.port,
            "username": conn.username,
            "password": "****",
            "database": conn.database,
            "project_id": str(conn.project_id) if conn.project_id else None,
            "created_at": conn.created_at.isoformat() if conn.created_at else None,
            "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
        },
        "message": "ok",
    }


@router.put("/{conn_id}")
async def update_database(
    conn_id: str,
    req: DatabaseConnectionUpdate,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """更新数据库连接。"""
    from app.models.database import DatabaseConnection

    result = await db.execute(
        select(DatabaseConnection).where(DatabaseConnection.id == conn_id)
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Database connection not found")

    updatable = {
        "name", "db_type", "host", "port", "username", "database",
    }
    for field in updatable:
        value = getattr(req, field, None)
        if value is not None:
            setattr(conn, field, value)

    if req.password is not None and req.password:
        conn.password_encrypted = encrypt(req.password)

    conn.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(conn)

    return {
        "code": 0,
        "data": {
            "id": str(conn.id),
            "name": conn.name,
            "db_type": conn.db_type,
            "host": conn.host,
            "port": conn.port,
            "username": conn.username,
            "password": "****",
            "database": conn.database,
            "project_id": str(conn.project_id) if conn.project_id else None,
            "created_at": conn.created_at.isoformat() if conn.created_at else None,
            "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
        },
        "message": "ok",
    }


@router.delete("/{conn_id}")
async def delete_database(
    conn_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """删除数据库连接。"""
    from app.models.database import DatabaseConnection

    result = await db.execute(
        select(DatabaseConnection).where(DatabaseConnection.id == conn_id)
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Database connection not found")

    await db.delete(conn)
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.get("/{conn_id}/schema")
async def get_database_schema(
    conn_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    获取数据库表结构。

    尝试连接数据库获取表结构，失败时返回占位数据。
    """
    from app.models.database import DatabaseConnection

    result = await db.execute(
        select(DatabaseConnection).where(DatabaseConnection.id == conn_id)
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Database connection not found")

    # 尝试真实连接获取表结构
    tables = []
    try:
        from app.utils.crypto import decrypt

        password = ""
        try:
            password = decrypt(conn.password_encrypted) if conn.password_encrypted else ""
        except Exception:
            password = conn.password_encrypted

        if conn.db_type == "postgresql":
            import asyncpg
            pool = await asyncpg.create_pool(
                host=conn.host,
                port=conn.port,
                user=conn.username,
                password=password,
                database=conn.database,
                min_size=1,
                max_size=1,
            )
            async with pool.acquire() as conn_pg:
                rows = await conn_pg.fetch(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                )
                for row in rows:
                    table_name = row["table_name"]
                    cols = await conn_pg.fetch(
                        f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{table_name}'"
                    )
                    tables.append({
                        "name": table_name,
                        "columns": [
                            {"name": c["column_name"], "type": c["data_type"]}
                            for c in cols
                        ],
                    })
            await pool.close()
        elif conn.db_type == "mysql":
            import aiomysql
            pool = await aiomysql.create_pool(
                host=conn.host,
                port=conn.port,
                user=conn.username,
                password=password,
                db=conn.database,
                minsize=1,
                maxsize=1,
            )
            async with pool.acquire() as conn_my:
                async with conn_my.cursor() as cur:
                    await cur.execute("SHOW TABLES")
                    rows = await cur.fetchall()
                    for row in rows:
                        table_name = row[0]
                        await cur.execute(f"DESCRIBE `{table_name}`")
                        cols = await cur.fetchall()
                        tables.append({
                            "name": table_name,
                            "columns": [
                                {"name": c[0], "type": c[1]} for c in cols
                            ],
                        })
            pool.close()
            await pool.wait_closed()
    except Exception as e:
        tables = [{"name": "schema_unavailable", "columns": [], "error": str(e)}]

    return {"code": 0, "data": {"tables": tables}, "message": "ok"}