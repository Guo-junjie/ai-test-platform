"""
审计日志模块

提供：
- AuditService: 审计日志 CRUD、操作记录、统计分析
"""

from app.modules.audit.audit_service import AuditService

__all__ = ["AuditService"]
