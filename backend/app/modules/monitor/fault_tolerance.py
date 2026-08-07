"""
容错处理器 — 故障识别、重试策略、兜底策略

定义 8 种故障类型和对应的处理策略（重试 + 兜底）。
兜底策略包括：使用缓存快照、标记超时、使用默认环境、从检查点恢复、切换备用模型。
"""

import time
from enum import Enum
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


class FaultType(Enum):
    """故障类型枚举。"""

    PULL_FAILURE = "pull_failure"          # 代码拉取失败
    SVN_AUTH_FAILURE = "svn_auth_failure"  # SVN 认证失败
    UPLOAD_CORRUPTED = "upload_corrupted"  # 上传文件损坏
    API_TIMEOUT = "api_timeout"            # API 请求超时
    ENV_EXCEPTION = "env_exception"        # 环境启动异常
    TASK_INTERRUPT = "task_interrupt"      # 任务中断
    AI_RATE_LIMIT = "ai_rate_limit"        # AI 调用频率限制
    DISK_FULL = "disk_full"                # 磁盘空间不足


# ==================== 故障策略配置 ====================

FAULT_STRATEGIES: dict[FaultType, dict[str, Any]] = {
    FaultType.PULL_FAILURE: {
        "max_retries": 3,
        "backoff_base": 5.0,
        "backoff_max": 30.0,
        "fallback": "use_cached_snapshot",
        "description": "代码拉取失败，重试后使用缓存快照",
    },
    FaultType.SVN_AUTH_FAILURE: {
        "max_retries": 0,  # 认证失败不重试
        "backoff_base": 0.0,
        "backoff_max": 0.0,
        "fallback": "mark_as_failed",
        "description": "SVN 认证失败，不重试，直接标记失败",
    },
    FaultType.UPLOAD_CORRUPTED: {
        "max_retries": 1,
        "backoff_base": 2.0,
        "backoff_max": 10.0,
        "fallback": "mark_as_failed",
        "description": "上传文件损坏，重试一次后标记失败",
    },
    FaultType.API_TIMEOUT: {
        "max_retries": 3,
        "backoff_base": 3.0,
        "backoff_max": 20.0,
        "fallback": "mark_as_timeout",
        "description": "API 请求超时，重试后标记超时",
    },
    FaultType.ENV_EXCEPTION: {
        "max_retries": 2,
        "backoff_base": 5.0,
        "backoff_max": 30.0,
        "fallback": "use_default_env",
        "description": "环境启动异常，重试后使用默认环境",
    },
    FaultType.TASK_INTERRUPT: {
        "max_retries": 2,
        "backoff_base": 10.0,
        "backoff_max": 60.0,
        "fallback": "resume_from_checkpoint",
        "description": "任务中断，重试后从检查点恢复",
    },
    FaultType.AI_RATE_LIMIT: {
        "max_retries": 5,
        "backoff_base": 10.0,
        "backoff_max": 120.0,
        "fallback": "switch_to_backup_model",
        "description": "AI 调用频率限制，重试后切换备用模型",
    },
    FaultType.DISK_FULL: {
        "max_retries": 0,
        "backoff_base": 0.0,
        "backoff_max": 0.0,
        "fallback": "mark_as_failed",
        "description": "磁盘空间不足，不重试，直接标记失败",
    },
}


class FaultHandler:
    """
    容错处理器。

    根据故障类型执行重试或兜底策略。
    """

    def handle(
        self, fault_type: FaultType, context: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行故障处理。

        根据故障类型查找策略，返回处理决策。

        Args:
            fault_type: 故障类型。
            context: 故障上下文（含 attempt, error, test_run_id 等）。

        Returns:
            处理决策字典: {action, retry, delay, fallback, message}。
        """
        strategy = FAULT_STRATEGIES.get(fault_type, FAULT_STRATEGIES[FaultType.TASK_INTERRUPT])
        attempt = context.get("attempt", 0)
        max_retries = strategy.get("max_retries", 0)

        logger.warning(
            f"Fault detected: {fault_type.value} (attempt={attempt}, "
            f"max_retries={max_retries}), strategy: {strategy.get('description', '')}"
        )

        if self.should_retry(fault_type, attempt):
            delay = self.get_backoff_delay(fault_type, attempt)
            return {
                "action": "retry",
                "retry": True,
                "delay": delay,
                "fallback": None,
                "message": f"Retrying after {delay:.1f}s (attempt {attempt + 1}/{max_retries})",
            }

        # 不再重试，执行兜底策略
        fallback = strategy.get("fallback", "mark_as_failed")
        return {
            "action": "fallback",
            "retry": False,
            "delay": 0,
            "fallback": fallback,
            "message": f"Max retries exceeded, applying fallback: {fallback}",
        }

    def should_retry(self, fault_type: FaultType, attempt: int) -> bool:
        """
        判断是否应该重试。

        Args:
            fault_type: 故障类型。
            attempt: 当前重试次数（0 = 首次失败）。

        Returns:
            True 表示应该重试。
        """
        strategy = FAULT_STRATEGIES.get(fault_type, {})
        max_retries = strategy.get("max_retries", 0)
        return attempt < max_retries

    def get_backoff_delay(self, fault_type: FaultType, attempt: int) -> float:
        """
        计算指数退避延迟。

        Args:
            fault_type: 故障类型。
            attempt: 当前重试次数。

        Returns:
            延迟时间（秒）。
        """
        strategy = FAULT_STRATEGIES.get(fault_type, {})
        base = strategy.get("backoff_base", 5.0)
        max_delay = strategy.get("backoff_max", 30.0)

        delay = min(base * (2 ** attempt), max_delay)
        return delay

    def get_fallback_strategy(self, fault_type: FaultType) -> str:
        """
        获取兜底策略名称。

        Args:
            fault_type: 故障类型。

        Returns:
            兜底策略名称。
        """
        strategy = FAULT_STRATEGIES.get(fault_type, {})
        return strategy.get("fallback", "mark_as_failed")
