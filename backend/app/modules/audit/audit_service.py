"""
审计日志服务 — 操作记录、查询过滤、统计分析

所有关键操作（创建/删除测试任务、修改配置、用户管理等）均通过
AuditService.log_action() 记录审计日志，支持按用户、操作类型、
资源类型、时间范围过滤查询。
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AuditLog
from app.utils.database import AsyncSessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AuditService:
    """
    审计日志服务。

    提供审计日志的创建、查询、统计功能。
    所有方法均为 async，使用 AsyncSession 操作数据库。
    """

    # ==================== 记录审计日志 ====================

    @staticmethod
    async def log_action(
        user_id: str | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        db: AsyncSession | None = None,
    ) -> AuditLog | None:
        """
        记录一条审计日志。

        Args:
            user_id: 操作用户 ID（系统操作时为 None）。
            action: 操作类型（如 create_test_run, delete_project）。
            resource_type: 资源类型（如 project, test_run, model_config）。
            resource_id: 资源 ID。
            details: 操作详情。
            ip_address: 请求来源 IP。
            db: 数据库会话，为 None 时自动创建。

        Returns:
            创建的 AuditLog 对象，失败返回 None。
        """
        async def _log(session: AsyncSession) -> AuditLog | None:
            try:
                log = AuditLog(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_id) if user_id else None,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details or {},
                    ip_address=ip_address,
                )
                session.add(log)
                await session.commit()
                return log
            except Exception as e:
                logger.error(f"Failed to log audit action '{action}': {e}")
                await session.rollback()
                return None

        if db is not None:
            return await _log(db)
        async with AsyncSessionLocal() as session:
            return await _log(session)

    @staticmethod
    async def log_from_request(
        request,
        user_id: str | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        从 FastAPI Request 对象记录审计日志（自动提取 IP）。

        Args:
            request: FastAPI Request 对象。
            user_id: 操作用户 ID。
            action: 操作类型。
            resource_type: 资源类型。
            resource_id: 资源 ID。
            details: 操作详情。
        """
        ip = request.client.host if request.client else None
        await AuditService.log_action(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip,
        )

    # ==================== 查询审计日志 ====================

    @staticmethod
    async def list_logs(
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        分页查询审计日志，支持多条件过滤。

        Args:
            user_id: 按用户过滤。
            action: 按操作类型过滤（精确匹配）。
            resource_type: 按资源类型过滤。
            start_date: 开始时间。
            end_date: 结束时间。
            page: 页码。
            page_size: 每页数量。
            db: 数据库会话。

        Returns:
            {"list": [...], "total": int, "page": int, "page_size": int}
        """
        async def _query(session: AsyncSession) -> dict[str, Any]:
            conditions = []
            if user_id:
                conditions.append(AuditLog.user_id == uuid.UUID(user_id))
            if action:
                conditions.append(AuditLog.action == action)
            if resource_type:
                conditions.append(AuditLog.resource_type == resource_type)
            if start_date:
                conditions.append(AuditLog.created_at >= start_date)
            if end_date:
                conditions.append(AuditLog.created_at <= end_date)

            # 总数查询
            count_query = select(func.count(AuditLog.id))
            if conditions:
                count_query = count_query.where(and_(*conditions))
            count_result = await session.execute(count_query)
            total = count_result.scalar() or 0

            # 分页查询
            offset = (page - 1) * page_size
            query = (
                select(AuditLog)
                .order_by(desc(AuditLog.created_at))
                .offset(offset)
                .limit(page_size)
            )
            if conditions:
                query = query.where(and_(*conditions))

            result = await session.execute(query)
            logs = result.scalars().all()

            # 关联查询用户名
            user_map: dict[str, str] = {}
            if logs:
                from app.models.database import User

                user_ids = {
                    str(log.user_id) for log in logs if log.user_id
                }
                if user_ids:
                    user_result = await session.execute(
                        select(User).where(User.id.in_([uuid.UUID(uid) for uid in user_ids]))
                    )
                    for u in user_result.scalars().all():
                        user_map[str(u.id)] = u.username

            return {
                "list": [
                    {
                        "id": str(log.id),
                        "user_id": str(log.user_id) if log.user_id else None,
                        "username": user_map.get(str(log.user_id), "system") if log.user_id else "system",
                        "action": log.action,
                        "resource_type": log.resource_type,
                        "resource_id": log.resource_id,
                        "details": log.details,
                        "ip_address": log.ip_address,
                        "created_at": log.created_at.isoformat() if log.created_at else None,
                    }
                    for log in logs
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

        if db is not None:
            return await _query(db)
        async with AsyncSessionLocal() as session:
            return await _query(session)

    # ==================== 统计分析 ====================

    @staticmethod
    async def get_statistics(
        days: int = 30,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        获取审计日志统计信息。

        Args:
            days: 统计时间范围（天）。
            db: 数据库会话。

        Returns:
            {
                "total_logs": int,
                "by_action": {action: count},
                "by_resource_type": {resource_type: count},
                "top_users": [{"username": str, "count": int}],
            }
        """
        async def _stats(session: AsyncSession) -> dict[str, Any]:
            since = datetime.utcnow() - timedelta(days=days)

            # 总数
            count_result = await session.execute(
                select(func.count(AuditLog.id)).where(AuditLog.created_at >= since)
            )
            total_logs = count_result.scalar() or 0

            # 按操作类型统计
            action_result = await session.execute(
                select(AuditLog.action, func.count(AuditLog.id))
                .where(AuditLog.created_at >= since)
                .group_by(AuditLog.action)
                .order_by(desc(func.count(AuditLog.id)))
            )
            by_action = {row[0]: row[1] for row in action_result.fetchall()}

            # 按资源类型统计
            resource_result = await session.execute(
                select(AuditLog.resource_type, func.count(AuditLog.id))
                .where(AuditLog.created_at >= since)
                .group_by(AuditLog.resource_type)
                .order_by(desc(func.count(AuditLog.id)))
            )
            by_resource_type = {
                (row[0] or "unknown"): row[1]
                for row in resource_result.fetchall()
            }

            # 活跃用户 TOP 10
            from app.models.database import User

            user_result = await session.execute(
                select(AuditLog.user_id, func.count(AuditLog.id).label("cnt"))
                .where(AuditLog.created_at >= since)
                .group_by(AuditLog.user_id)
                .order_by(desc("cnt"))
                .limit(10)
            )
            top_user_rows = user_result.fetchall()

            top_users = []
            for row in top_user_rows:
                if row[0]:
                    u_result = await session.execute(
                        select(User).where(User.id == row[0])
                    )
                    u = u_result.scalar_one_or_none()
                    top_users.append({
                        "username": u.username if u else "unknown",
                        "count": row[1],
                    })

            return {
                "total_logs": total_logs,
                "days": days,
                "by_action": by_action,
                "by_resource_type": by_resource_type,
                "top_users": top_users,
            }

        if db is not None:
            return await _stats(db)
        async with AsyncSessionLocal() as session:
            return await _stats(session)
