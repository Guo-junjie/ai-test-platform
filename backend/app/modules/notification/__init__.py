"""
通知集成模块

提供：
- NotificationManager: 通知管理器，支持 webhook / 邮件 / 钉钉多渠道通知
"""

from app.modules.notification.notifier import NotificationManager

__all__ = ["NotificationManager"]
