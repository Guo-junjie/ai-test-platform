"""缺陷评论、关注人与私有附件。"""
import asyncio
import hashlib
import io
import os
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models.database import (
    Defect, DefectAttachment, DefectComment, DefectWatcher, ProjectDefectSettings,
    ProjectMember, User,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.defects.permissions import context_for
from app.modules.defects.service import append_event, json_value, snapshot
from app.schemas.defect_management import CommentInput, CommentUpdate, WatcherInput
from app.utils.database import get_db_session
from app.utils.storage import get_minio_client

router = APIRouter()
attachment_router = APIRouter()
MAX_ATTACHMENT = 20 * 1024 * 1024
MAX_DEFECT_TOTAL = 200 * 1024 * 1024
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".log", ".md", ".csv", ".json", ".xml", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
ALLOWED_MIME_PREFIXES = ("image/", "text/")
ALLOWED_MIMES = {"application/pdf", "application/json", "application/xml", "application/msword",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                 "application/octet-stream"}


def success(data, message="success"):
    return {"code": 0, "data": data, "message": message}


async def _defect(db, user, defect_id, *, lock=False):
    query = select(Defect).where(Defect.id == defect_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    item = (await db.execute(query)).scalar_one_or_none()
    if item is None or item.deleted_at:
        raise HTTPException(404, "缺陷不存在或已删除")
    context = await context_for(db, user, item.project_id, write=lock)
    return item, context


async def _validate_mentions(db, project, identifiers):
    if not identifiers:
        return []
    members = set((await db.execute(select(ProjectMember.user_id).where(
        ProjectMember.project_id == project.id))).scalars().all())
    members.add(project.owner_id)
    users = (await db.execute(select(User).where(User.id.in_(identifiers), User.is_active.is_(True)))).scalars().all()
    valid = {item.id for item in users if item.id in members}
    if valid != set(identifiers):
        raise HTTPException(422, "@提醒对象必须是当前项目的有效成员")
    return [str(value) for value in dict.fromkeys(identifiers)]


def _comment_dict(item, author_name, attachments=None):
    return {
        "id": str(item.id), "defect_id": str(item.defect_id), "author_id": str(item.author_id),
        "author_name": author_name, "body": "" if item.deleted_at else item.body,
        "mention_user_ids": [] if item.deleted_at else [str(value) for value in (item.mention_user_ids or [])],
        "row_version": item.row_version, "created_at": json_value(item.created_at),
        "edited_at": json_value(item.edited_at), "deleted_at": json_value(item.deleted_at),
        "attachments": attachments or [],
    }


@router.get("/{defect_id}/comments")
async def list_comments(defect_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    await _defect(db, user, defect_id)
    rows = (await db.execute(select(DefectComment, User.username).join(User, User.id == DefectComment.author_id)
            .where(DefectComment.defect_id == defect_id).order_by(DefectComment.created_at))).all()
    attachment_rows = (await db.execute(select(DefectAttachment).where(
        DefectAttachment.defect_id == defect_id, DefectAttachment.deleted_at.is_(None),
        DefectAttachment.comment_id.is_not(None)))).scalars().all()
    grouped = {}
    for item in attachment_rows:
        grouped.setdefault(item.comment_id, []).append(_attachment_dict(item))
    return success({"items": [_comment_dict(item, name, grouped.get(item.id)) for item, name in rows]})


async def _bind_attachments(db, defect, user, comment_id, attachment_ids):
    if not attachment_ids:
        return
    rows = (await db.execute(select(DefectAttachment).where(DefectAttachment.id.in_(attachment_ids)).with_for_update())).scalars().all()
    if len(rows) != len(attachment_ids):
        raise HTTPException(422, "部分附件不存在")
    for item in rows:
        if item.project_id != defect.project_id or item.uploader_id != user.id or item.status != "staged" or item.deleted_at:
            raise HTTPException(422, "附件不属于当前用户、项目或已失效")
        if item.expires_at and item.expires_at < datetime.now(timezone.utc):
            raise HTTPException(422, "附件暂存已过期，请重新上传")
        item.defect_id = defect.id
        item.comment_id = comment_id
        item.status = "ready"
        item.expires_at = None


@router.post("/{defect_id}/comments")
async def create_comment(defect_id: UUID, req: CommentInput, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, _ = await _defect(db, user, defect_id, lock=True)
    mentions = await _validate_mentions(db, (await context_for(db, user, defect.project_id)).project, req.mention_user_ids)
    item = DefectComment(id=uuid4(), defect_id=defect.id, project_id=defect.project_id, author_id=user.id,
                         body=req.body, mention_user_ids=mentions, row_version=1)
    db.add(item)
    await db.flush()
    await _bind_attachments(db, defect, user, item.id, req.attachment_ids)
    event = append_event(db, defect, user, "comment_added", snapshot(defect), note=req.body[:500],
                         extra={"comment_id": str(item.id), "mention_user_ids": mentions})
    await db.commit()
    return success(_comment_dict(item, user.username), "评论已发布")


@router.patch("/{defect_id}/comments/{comment_id}")
async def update_comment(defect_id: UUID, comment_id: UUID, req: CommentUpdate, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, context = await _defect(db, user, defect_id, lock=True)
    item = (await db.execute(select(DefectComment).where(DefectComment.id == comment_id,
            DefectComment.defect_id == defect.id).with_for_update())).scalar_one_or_none()
    if not item or item.deleted_at:
        raise HTTPException(404, "评论不存在")
    if item.author_id != user.id:
        raise HTTPException(403, "只能编辑自己的评论")
    if item.row_version != req.expected_version:
        raise HTTPException(409, "评论已被更新，请刷新后重试")
    mentions = await _validate_mentions(db, context.project, req.mention_user_ids)
    item.body, item.mention_user_ids = req.body, mentions
    item.row_version += 1
    item.edited_at = datetime.now(timezone.utc)
    append_event(db, defect, user, "comment_updated", snapshot(defect), note=req.body[:500],
                 extra={"comment_id": str(item.id), "mention_user_ids": mentions})
    await db.commit()
    return success(_comment_dict(item, user.username), "评论已更新")


@router.delete("/{defect_id}/comments/{comment_id}")
async def delete_comment(defect_id: UUID, comment_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, context = await _defect(db, user, defect_id, lock=True)
    item = (await db.execute(select(DefectComment).where(DefectComment.id == comment_id,
            DefectComment.defect_id == defect.id).with_for_update())).scalar_one_or_none()
    if not item or item.deleted_at:
        raise HTTPException(404, "评论不存在")
    if item.author_id != user.id and not context.privileged:
        raise HTTPException(403, "只能删除自己的评论")
    item.deleted_at = datetime.now(timezone.utc)
    item.row_version += 1
    append_event(db, defect, user, "comment_deleted", snapshot(defect), extra={"comment_id": str(item.id)})
    await db.commit()
    return success({"id": str(item.id)}, "评论已删除")


@router.get("/{defect_id}/watchers")
async def list_watchers(defect_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    await _defect(db, user, defect_id)
    rows = (await db.execute(select(DefectWatcher, User.username).join(User, User.id == DefectWatcher.user_id)
            .where(DefectWatcher.defect_id == defect_id).order_by(DefectWatcher.created_at))).all()
    return success({"items": [{"id": str(item.id), "user_id": str(item.user_id), "username": name, "kind": item.kind,
                                "created_at": json_value(item.created_at)} for item, name in rows]})


@router.post("/{defect_id}/watchers")
async def add_watcher(defect_id: UUID, req: WatcherInput, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, context = await _defect(db, user, defect_id, lock=True)
    target = req.user_id or user.id
    if (target != user.id or req.kind == "cc") and not context.privileged:
        raise HTTPException(403, "添加抄送人或代他人关注需要项目负责人权限")
    await _validate_mentions(db, context.project, [target])
    existing = (await db.execute(select(DefectWatcher).where(DefectWatcher.defect_id == defect.id,
                DefectWatcher.user_id == target, DefectWatcher.kind == req.kind))).scalar_one_or_none()
    if existing is None:
        existing = DefectWatcher(id=uuid4(), defect_id=defect.id, project_id=defect.project_id,
                                  user_id=target, kind=req.kind, created_by=user.id)
        db.add(existing)
        append_event(db, defect, user, "watcher_added", snapshot(defect),
                     extra={"user_id": str(target), "kind": req.kind, "mention_user_ids": [target] if target != user.id else []})
    await db.commit()
    return success({"id": str(existing.id), "user_id": str(target), "kind": req.kind})


@router.delete("/{defect_id}/watchers/{watcher_id}")
async def remove_watcher(defect_id: UUID, watcher_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, context = await _defect(db, user, defect_id, lock=True)
    item = (await db.execute(select(DefectWatcher).where(DefectWatcher.id == watcher_id,
            DefectWatcher.defect_id == defect.id))).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "关注记录不存在")
    if item.user_id != user.id and not context.privileged:
        raise HTTPException(403, "只能取消自己的关注")
    await db.delete(item)
    append_event(db, defect, user, "watcher_removed", snapshot(defect), extra={"user_id": str(item.user_id), "kind": item.kind})
    await db.commit()
    return success({"id": str(watcher_id)})


def _attachment_dict(item):
    return {"id": str(item.id), "defect_id": str(item.defect_id) if item.defect_id else None,
            "comment_id": str(item.comment_id) if item.comment_id else None, "filename": item.filename,
            "content_type": item.content_type, "size": item.size, "sha256": item.sha256,
            "status": item.status, "created_at": json_value(item.created_at),
            "download_url": f"/api/defect-attachments/{item.id}/download" if item.status == "ready" else None}


def _check_file(filename, content_type, data):
    extension = PurePath(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "不支持此附件类型；禁止可执行文件与压缩包")
    if not (content_type.startswith(ALLOWED_MIME_PREFIXES) or content_type in ALLOWED_MIMES):
        raise HTTPException(415, "附件 Content-Type 不受支持")
    signatures = {".pdf": b"%PDF", ".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8", ".gif": b"GIF"}
    expected = signatures.get(extension)
    if expected and not data.startswith(expected):
        raise HTTPException(415, "附件内容与扩展名不一致")
    if extension in {".docx", ".xlsx", ".pptx"} and not data.startswith(b"PK"):
        raise HTTPException(415, "Office 附件格式无效")
    if extension in {".doc", ".xls", ".ppt"} and not data.startswith(b"\xd0\xcf\x11\xe0"):
        raise HTTPException(415, "Office 附件格式无效")
    if extension in {".txt", ".log", ".md", ".csv", ".json", ".xml"}:
        try:
            decoded = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(415, "文本附件必须使用 UTF-8 编码")
        if "\x00" in decoded:
            raise HTTPException(415, "文本附件内容无效")


@attachment_router.post("")
async def upload_attachment(project_id: UUID = Form(...), defect_id: UUID | None = Form(None),
                            file: UploadFile = File(...), db=Depends(get_db_session), user=Depends(get_current_user)):
    context = await context_for(db, user, project_id, write=True)
    defect = None
    if defect_id:
        defect, _ = await _defect(db, user, defect_id, lock=True)
        if defect.project_id != project_id:
            raise HTTPException(422, "缺陷不属于所选项目")
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_ATTACHMENT:
            raise HTTPException(413, "单个附件不能超过 20MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(422, "附件不能为空")
    filename = os.path.basename(file.filename or "attachment")[:500]
    content_type = (file.content_type or "application/octet-stream").lower()
    _check_file(filename, content_type, data)
    if defect:
        used = (await db.execute(select(func.coalesce(func.sum(DefectAttachment.size), 0)).where(
            DefectAttachment.defect_id == defect.id, DefectAttachment.deleted_at.is_(None),
            DefectAttachment.status.in_(["ready", "staged"])))).scalar_one()
        project_settings = await db.get(ProjectDefectSettings, project_id)
        limit = int((project_settings.field_config or {}).get("attachment_limit_bytes", MAX_DEFECT_TOTAL)) if project_settings else MAX_DEFECT_TOTAL
        if used + total > min(limit, MAX_DEFECT_TOTAL):
            raise HTTPException(413, "该缺陷附件总量不能超过 200MB")
    identifier = uuid4()
    object_key = f"defects/{project_id}/{defect_id or 'staged'}/{identifier}/{filename}"
    client = get_minio_client()
    try:
        await asyncio.to_thread(client.put_object, settings.MINIO_BUCKET, object_key, io.BytesIO(data), total, content_type=content_type)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"附件存储暂不可用：{str(exc)[:160]}")
    item = DefectAttachment(id=identifier, project_id=project_id, defect_id=defect_id, uploader_id=user.id,
                            filename=filename, content_type=content_type, size=total,
                            sha256=hashlib.sha256(data).hexdigest(), object_key=object_key,
                            status="ready" if defect else "staged",
                            expires_at=None if defect else datetime.now(timezone.utc) + timedelta(hours=24))
    db.add(item)
    if defect:
        append_event(db, defect, user, "attachment_added", snapshot(defect), extra={"attachment_id": str(identifier), "filename": filename})
    await db.commit()
    return success(_attachment_dict(item), "附件已上传")


@router.get("/{defect_id}/attachments")
async def list_attachments(defect_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    await _defect(db, user, defect_id)
    rows = (await db.execute(select(DefectAttachment).where(DefectAttachment.defect_id == defect_id,
            DefectAttachment.deleted_at.is_(None), DefectAttachment.status == "ready")
            .order_by(DefectAttachment.created_at.desc()))).scalars().all()
    return success({"items": [_attachment_dict(item) for item in rows]})


@attachment_router.get("/{attachment_id}/download")
async def download_attachment(attachment_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    item = await db.get(DefectAttachment, attachment_id)
    if not item or item.status != "ready" or item.deleted_at:
        raise HTTPException(404, "附件不存在")
    await context_for(db, user, item.project_id)
    try:
        response = await asyncio.to_thread(get_minio_client().get_object, settings.MINIO_BUCKET, item.object_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"附件读取失败：{str(exc)[:160]}")

    def stream():
        try:
            for chunk in response.stream(64 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()
    safe = item.filename.replace('"', "'").replace("\r", "").replace("\n", "")
    return StreamingResponse(stream(), media_type=item.content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@attachment_router.delete("/{attachment_id}")
async def delete_attachment(attachment_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    item = await db.get(DefectAttachment, attachment_id)
    if not item or item.deleted_at:
        raise HTTPException(404, "附件不存在")
    context = await context_for(db, user, item.project_id, write=True)
    if item.uploader_id != user.id and not context.privileged:
        raise HTTPException(403, "只能删除自己上传的附件")
    defect = None
    if item.defect_id:
        defect, _ = await _defect(db, user, item.defect_id, lock=True)
    try:
        await asyncio.to_thread(get_minio_client().remove_object, settings.MINIO_BUCKET, item.object_key)
    except Exception:
        pass
    item.deleted_at = datetime.now(timezone.utc)
    item.status = "deleted"
    if defect:
        append_event(db, defect, user, "attachment_deleted", snapshot(defect), extra={"attachment_id": str(item.id), "filename": item.filename})
    await db.commit()
    return success({"id": str(item.id)})
