"""
通知管理器 — 多渠道消息通知

支持三种通知渠道：
- Webhook: 通用 HTTP POST 回调
- Email: SMTP 邮件通知
- DingTalk: 钉钉机器人消息

通知场景：
- 质量门禁未通过
- 测试任务失败
- P0 缺陷发现
- 测试报告生成完成
"""

import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

import httpx
from loguru import logger

from app.config import settings


# ==================== 通知事件类型 ====================

EVENT_TEMPLATES: dict[str, dict[str, str]] = {
    "gate_failed": {
        "title": "质量门禁未通过",
        "template": (
            "⚠️ 质量门禁未通过\n"
            "项目: {project_name}\n"
            "测试任务: {test_run_id}\n"
            "质量评分: {quality_score}\n"
            "违规项: {violations}\n"
            "请及时处理！"
        ),
    },
    "test_failed": {
        "title": "测试任务失败",
        "template": (
            "❌ 测试任务执行失败\n"
            "测试任务: {test_run_id}\n"
            "错误信息: {error_message}\n"
            "请检查并重试。"
        ),
    },
    "p0_defect_found": {
        "title": "发现 P0 级缺陷",
        "template": (
            "🚨 发现 {p0_count} 个 P0 级缺陷\n"
            "测试任务: {test_run_id}\n"
            "缺陷详情: {defect_details}\n"
            "请立即处理！"
        ),
    },
    "report_generated": {
        "title": "测试报告已生成",
        "template": (
            "✅ 测试报告已生成\n"
            "测试任务: {test_run_id}\n"
            "质量评分: {quality_score}\n"
            "查看报告: {report_url}\n"
            "门禁结果: {'通过' if gate_passed else '未通过'}"
        ),
    },
}


class NotificationManager:
    """
    通知管理器。

    根据事件类型和配置的渠道发送通知消息。
    """

    def __init__(
        self,
        webhook_url: str = "",
        dingtalk_webhook: str = "",
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        email_from: str = "",
        email_to: list[str] | None = None,
    ) -> None:
        """
        初始化通知管理器。

        Args:
            webhook_url: 通用 Webhook 回调 URL。
            dingtalk_webhook: 钉钉机器人 Webhook URL。
            smtp_host: SMTP 服务器地址。
            smtp_port: SMTP 端口。
            smtp_user: SMTP 用户名。
            smtp_password: SMTP 密码。
            email_from: 发件人邮箱。
            email_to: 默认收件人列表。
        """
        self.webhook_url = webhook_url
        self.dingtalk_webhook = dingtalk_webhook
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.email_from = email_from
        self.email_to = email_to or []

    # ==================== 发送通知 ====================

    async def send_notification(
        self,
        event_type: str,
        data: dict[str, Any],
        channels: list[str] | None = None,
    ) -> dict[str, bool]:
        """
        发送通知消息。

        Args:
            event_type: 事件类型（gate_failed / test_failed / p0_defect_found / report_generated）。
            data: 事件数据，用于填充消息模板。
            channels: 通知渠道列表，为 None 时使用所有已配置渠道。

        Returns:
            {channel_name: success_bool} 字典。
        """
        template_info = EVENT_TEMPLATES.get(event_type)
        if template_info is None:
            # 未注册的事件类型，使用通用格式
            title = event_type
            message = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        else:
            title = template_info["title"]
            try:
                message = template_info["template"].format(**data)
            except KeyError as e:
                logger.warning(f"Notification template missing key: {e}")
                message = json.dumps(data, ensure_ascii=False, indent=2, default=str)

        if channels is None:
            channels = []
            if self.webhook_url:
                channels.append("webhook")
            if self.dingtalk_webhook:
                channels.append("dingtalk")
            if self.smtp_host and self.email_to:
                channels.append("email")

        results: dict[str, bool] = {}

        for channel in channels:
            try:
                if channel == "webhook":
                    results["webhook"] = await self._send_webhook(
                        title, message, data
                    )
                elif channel == "dingtalk":
                    results["dingtalk"] = await self._send_dingtalk(title, message)
                elif channel == "email":
                    results["email"] = await self._send_email(title, message)
                else:
                    logger.warning(f"Unknown notification channel: {channel}")
                    results[channel] = False
            except Exception as e:
                logger.error(f"Notification via {channel} failed: {e}")
                results[channel] = False

        logger.info(
            f"Notification sent: event={event_type}, channels={channels}, "
            f"results={results}"
        )
        return results

    # ==================== Webhook 渠道 ====================

    async def _send_webhook(
        self,
        title: str,
        message: str,
        data: dict[str, Any],
    ) -> bool:
        """
        通过通用 Webhook 发送通知。

        POST JSON: {"title": ..., "message": ..., "data": ..., "timestamp": ...}
        """
        if not self.webhook_url:
            return False

        payload = {
            "title": title,
            "message": message,
            "data": data,
            "source": "ai-test-platform",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            return response.status_code < 400

    # ==================== 钉钉渠道 ====================

    async def _send_dingtalk(self, title: str, message: str) -> bool:
        """
        通过钉钉机器人 Webhook 发送通知。

        使用钉钉 markdown 消息格式。
        """
        if not self.dingtalk_webhook:
            return False

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"### {title}\n\n{message}",
            },
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.dingtalk_webhook,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code < 400:
                result = response.json()
                return result.get("errcode", -1) == 0
            return False

    # ==================== 邮件渠道 ====================

    def _send_email(self, title: str, message: str) -> bool:
        """
        通过 SMTP 发送邮件通知。

        使用同步 SMTP（在通知场景下调用频率低，可接受）。
        """
        if not self.smtp_host or not self.email_to:
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[AI测试平台] {title}"
            msg["From"] = self.email_from or self.smtp_user
            msg["To"] = ", ".join(self.email_to)

            # 纯文本
            text_part = MIMEText(message, "plain", "utf-8")
            msg.attach(text_part)

            # HTML
            html_content = (
                f"<html><body>"
                f"<h2>{title}</h2>"
                f"<pre style='font-family: monospace; "
                f"white-space: pre-wrap; word-wrap: break-word;'>"
                f"{message}</pre>"
                f"<hr><p style='color: #999; font-size: 12px;'>"
                f"此邮件由 AI 自动化测试平台自动发送</p>"
                f"</body></html>"
            )
            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(
                    self.email_from or self.smtp_user,
                    self.email_to,
                    msg.as_string(),
                )

            return True
        except Exception as e:
            logger.error(f"Email notification failed: {e}")
            return False

    # ==================== 便捷方法 ====================

    @classmethod
    def from_settings(cls) -> "NotificationManager":
        """从环境变量创建通知管理器实例。"""
        import os

        return cls(
            webhook_url=os.getenv("NOTIFY_WEBHOOK_URL", ""),
            dingtalk_webhook=os.getenv("NOTIFY_DINGTALK_WEBHOOK", ""),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            email_from=os.getenv("SMTP_FROM", ""),
            email_to=[
                addr.strip()
                for addr in os.getenv("NOTIFY_EMAIL_TO", "").split(",")
                if addr.strip()
            ],
        )
