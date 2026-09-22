"""由项目负责人或管理员显式授权，不默认开放历史项目。"""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from app.models.database import Project, ProjectMember, User, AuditLog
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.project_scope import ADMIN_ROLES
from app.utils.database import get_db_session

router = APIRouter()


async def require_project_manager(project_id: UUID, db, user):
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "项目不存在或无权访问")
    if user.role not in ADMIN_ROLES and project.owner_id != user.id:
        raise HTTPException(403, "仅项目负责人或管理员可管理成员")
    return project


class MemberRequest(BaseModel):
    username: str
    access: Literal["read", "write"] = "read"


@router.get("/{project_id}/members")
async def list_members(project_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    project = await require_project_manager(project_id, db, user)
    members = (await db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
                               .where(ProjectMember.project_id == project_id))).all()
    return {"code": 0, "data": {"owner_id": str(project.owner_id), "items": [
        {"user_id": str(member.user_id), "username": account.username,
         "role": account.role.value, "access": member.access, "is_active": account.is_active}
        for member, account in members
    ]}, "message": "success"}


@router.put("/{project_id}/members")
async def set_member(project_id: UUID, req: MemberRequest, db=Depends(get_db_session), user=Depends(get_current_user)):
    project = await require_project_manager(project_id, db, user)
    account = (await db.execute(select(User).where(User.username == req.username.strip(), User.is_active.is_(True)))).scalar_one_or_none()
    if account is None:
        raise HTTPException(404, "未找到启用的用户，请先由管理员创建账号")
    if account.id == project.owner_id:
        raise HTTPException(400, "负责人已拥有项目权限，无需重复添加")
    member = await db.get(ProjectMember, (project_id, account.id))
    if member is None:
        member = ProjectMember(project_id=project_id, user_id=account.id)
        db.add(member)
    member.access = req.access
    db.add(AuditLog(user_id=user.id, action="project_member_granted", resource_type="project",
                    resource_id=str(project_id), details={"member_id": str(account.id), "access": req.access}))
    await db.commit()
    return {"code": 0, "message": "成员权限已保存，全局角色仍限制可执行操作"}


@router.delete("/{project_id}/members/{user_id}")
async def remove_member(project_id: UUID, user_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    await require_project_manager(project_id, db, user)
    member = await db.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise HTTPException(404, "项目成员不存在")
    await db.delete(member)
    db.add(AuditLog(user_id=user.id, action="project_member_revoked", resource_type="project",
                    resource_id=str(project_id), details={"member_id": str(user_id)}))
    await db.commit()
    return {"code": 0, "message": "已撤销项目权限"}
