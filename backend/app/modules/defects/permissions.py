"""缺陷职责与现有全局/项目边界取交集。"""
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models.database import Project, ProjectDefectSettings, ProjectMember, ProjectDefectRole, User, UserRole
from app.modules.auth.project_scope import ADMIN_ROLES


@dataclass
class DefectContext:
    project: Project
    user: User
    roles: set[str]
    writable: bool
    permission_config: dict = field(default_factory=dict)

    @property
    def privileged(self):
        return bool(self.roles & {"project_manager", "qa_lead"}) and self.writable


async def context_for(db, user, project_id: UUID, *, write=False):
    if user.role == UserRole.AUDITOR:
        raise HTTPException(403, "合规审计账号不可访问缺陷业务")
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "项目不存在或无权访问")
    member = (await db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                          ProjectMember.user_id == user.id))).scalar_one_or_none()
    owner = project.owner_id == user.id
    admin = user.role in ADMIN_ROLES
    if not (admin or owner or member):
        raise HTTPException(404, "项目不存在或无权访问")
    writable = bool(admin or owner or (member and member.access == "write")) and user.role != UserRole.VIEWER
    roles = set()
    if writable:
        if admin or owner:
            roles.add("project_manager")
        defaults = {UserRole.TEST_MANAGER: "qa_lead", UserRole.TESTER: "qa", UserRole.DEVELOPER: "developer"}
        if user.role in defaults:
            roles.add(defaults[user.role])
        roles.update((await db.execute(select(ProjectDefectRole.role_key).where(
            ProjectDefectRole.project_id == project_id, ProjectDefectRole.user_id == user.id))).scalars().all())
    if write and not writable:
        raise HTTPException(403, "没有此项目的缺陷写入权限")
    settings = await db.get(ProjectDefectSettings, project_id)
    return DefectContext(project, user, roles, writable, (settings.permission_config or {}) if settings else {})


def can_edit(context, defect):
    reporter_allowed = context.permission_config.get("allow_reporter_edit", True)
    developer_allowed = context.permission_config.get("allow_developer_edit_assigned", True)
    return context.writable and (context.privileged or (reporter_allowed and defect.reporter_id == context.user.id)
                                 or (developer_allowed and "developer" in context.roles and defect.assignee_id == context.user.id))


def action_denial(context, defect, action):
    if not context.writable:
        return "当前项目或全局角色只允许查看"
    if not context.roles.intersection(action["roles"]):
        return "当前项目职责不能执行该动作"
    relations = set()
    if "project_manager" in context.roles:
        relations.add("project_manager")
    if "qa_lead" in context.roles:
        relations.add("qa_lead")
    if context.privileged:
        relations.add("privileged_override")
    if defect.assignee_id == context.user.id:
        relations.add("assignee")
    if defect.verifier_id == context.user.id:
        relations.add("verifier")
    if defect.reporter_id == context.user.id:
        relations.add("reporter")
    if not relations.intersection(action["actor_relations"]):
        return "仅当前责任人或项目负责人可执行"
    return None


async def validate_participant(db, project, user_id, purpose):
    if user_id is None:
        return
    user = (await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))).scalar_one_or_none()
    if user is None:
        raise HTTPException(422, "所选人员不存在或已停用")
    member = (await db.execute(select(ProjectMember).where(ProjectMember.project_id == project.id,
                                                          ProjectMember.user_id == user.id))).scalar_one_or_none()
    if project.owner_id != user.id and (member is None or member.access != "write"):
        raise HTTPException(422, "处理或验证人员必须是本项目可写成员")
    context = await context_for(db, user, project.id)
    needed = {"assignee": {"developer", "project_manager", "qa_lead"},
              "verifier": {"qa", "qa_lead", "project_manager"}}[purpose]
    if not context.roles.intersection(needed):
        raise HTTPException(422, "所选人员没有对应的处理或验证职责")
