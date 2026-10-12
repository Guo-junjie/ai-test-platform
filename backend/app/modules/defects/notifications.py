"""缺陷通知 outbox：业务事务只入队，worker 幂等投递。"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select

from app.models.database import (
    Defect, DefectWatcher, Notification, NotificationDelivery, NotificationOutbox,
    Project, ProjectDefectSettings, ProjectMember, User, UserPreference, UserRole,
)
from app.utils.database import AsyncSessionLocal


EVENT_LABELS = {
    "created": "新建了缺陷", "updated": "更新了缺陷", "assigned": "调整了责任人",
    "comment_added": "发表了评论", "comment_updated": "编辑了评论", "comment_deleted": "删除了评论",
    "attachment_added": "上传了附件", "attachment_deleted": "删除了附件",
    "triage": "完成了分诊", "start": "开始处理", "resume": "继续处理", "submit_fix": "提交了修复",
    "verify_pass": "验证通过", "verify_fail": "验证失败", "close": "关闭了缺陷", "reopen": "重开了缺陷",
    "reject": "拒绝了缺陷", "deleted": "删除了缺陷", "restored": "恢复了缺陷",
    "workflow_migrated": "迁移了工作流",
}


def enqueue_event(db, defect, event, actor, *, mention_user_ids=None):
    """与缺陷事件同事务写入；event_id 唯一保证重试不重复。"""
    db.add(NotificationOutbox(
        id=uuid4(), project_id=defect.project_id, event_id=event.id,
        payload={
            "defect_id": str(defect.id), "defect_key": defect.defect_key,
            "title": defect.title, "event_type": event.event_type,
            "actor_id": str(actor.id) if actor else None,
            "mention_user_ids": [str(value) for value in (mention_user_ids or [])],
            "note": event.note or "",
        },
        status="pending", next_attempt_at=datetime.now(timezone.utc),
    ))


async def _eligible_recipients(db, item, defect, payload, project_config):
    direct = {value for value in (defect.reporter_id, defect.assignee_id, defect.verifier_id) if value}
    direct.update((await db.execute(select(DefectWatcher.user_id).where(
        DefectWatcher.defect_id == defect.id))).scalars().all())
    for raw in payload.get("mention_user_ids") or []:
        try:
            from uuid import UUID
            direct.add(UUID(raw))
        except (ValueError, TypeError):
            continue
    for raw in project_config.get("default_watchers") or []:
        try:
            from uuid import UUID
            direct.add(UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    project = await db.get(Project, item.project_id)
    members = set((await db.execute(select(ProjectMember.user_id).where(
        ProjectMember.project_id == item.project_id))).scalars().all())
    if project:
        members.add(project.owner_id)
    if not direct:
        return []
    users = (await db.execute(select(User).where(User.id.in_(direct), User.is_active.is_(True)))).scalars().all()
    actor_id = payload.get("actor_id")
    return [user for user in users if (project_config.get("notify_actor") or str(user.id) != actor_id) and (
        user.id in members or user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
    )]


async def dispatch_outbox(limit=100):
    """锁定并投递一批；站内信可用，外部渠道明确记为失败而不伪报成功。"""
    now = datetime.now(timezone.utc)
    delivered = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(NotificationOutbox).where(
            NotificationOutbox.status.in_(["pending", "processing"]),
            NotificationOutbox.next_attempt_at <= now,
            or_(NotificationOutbox.locked_until.is_(None), NotificationOutbox.locked_until < now),
        ).order_by(NotificationOutbox.created_at).with_for_update(skip_locked=True).limit(limit))).scalars().all()
        for item in rows:
            item.status = "processing"
            item.locked_until = now + timedelta(minutes=2)
            item.attempts += 1
            try:
                payload = item.payload or {}
                defect = await db.get(Defect, payload.get("defect_id"))
                if not defect or defect.project_id != item.project_id:
                    item.status = "completed"
                    item.last_error = "资源已不存在"
                    continue
                settings_row = await db.get(ProjectDefectSettings, item.project_id)
                project_config = (settings_row.notification_config or {}) if settings_row else {}
                enabled_events = project_config.get("enabled_events") or ["*"]
                if "*" not in enabled_events and payload.get("event_type") not in enabled_events:
                    item.status = "completed"
                    item.last_error = "项目已关闭此事件通知"
                    continue
                recipients = await _eligible_recipients(db, item, defect, payload, project_config)
                for user in recipients:
                    preference = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
                    config = preference.notification_config if preference else {}
                    if config.get("enabled") is False:
                        continue
                    channels = config.get("channels") or ["in_app"]
                    for channel in channels:
                        delivery = (await db.execute(select(NotificationDelivery).where(
                            NotificationDelivery.outbox_id == item.id,
                            NotificationDelivery.user_id == user.id,
                            NotificationDelivery.channel == channel,
                        ))).scalar_one_or_none()
                        if delivery and delivery.status == "completed":
                            continue
                        if not delivery:
                            delivery = NotificationDelivery(id=uuid4(), outbox_id=item.id, user_id=user.id,
                                                            channel=channel, status="pending", attempts=0)
                            db.add(delivery)
                        delivery.attempts += 1
                        if channel != "in_app":
                            delivery.status = "failed"
                            delivery.last_error = "当前部署未配置此通知渠道"
                            continue
                        dedupe = f"defect:{item.event_id}:{user.id}:in_app"
                        existing = (await db.execute(select(Notification.id).where(Notification.dedupe_key == dedupe))).scalar_one_or_none()
                        if existing is None:
                            label = EVENT_LABELS.get(payload.get("event_type"), payload.get("event_type") or "更新了缺陷")
                            content = f"{payload.get('defect_key', '')} {payload.get('title', '')}"
                            if payload.get("note"):
                                content += "\n" + str(payload["note"])[:500]
                            db.add(Notification(id=uuid4(), user_id=user.id, title=label, content=content,
                                                type="defect", related_url=f"/defects/{defect.id}?project_id={defect.project_id}",
                                                source_event_id=item.event_id, resource_type="defect", resource_id=defect.id,
                                                dedupe_key=dedupe, created_at=datetime.utcnow()))
                        delivery.status = "completed"
                        delivery.delivered_at = now
                        delivery.last_error = None
                        delivered += 1
                item.status = "completed"
                item.locked_until = None
                item.last_error = None
            except Exception as exc:  # noqa: BLE001
                item.status = "failed" if item.attempts >= 5 else "pending"
                item.next_attempt_at = now + timedelta(seconds=min(300, 2 ** item.attempts * 10))
                item.locked_until = None
                item.last_error = str(exc)[:2000]
        await db.commit()
    return delivered


def run_dispatch():
    return asyncio.run(dispatch_outbox())
