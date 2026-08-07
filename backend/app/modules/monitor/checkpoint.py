"""
检查点管理器 — 使用 Redis 保存/恢复任务检查点

在测试执行过程中定期保存检查点，任务中断后可从最近检查点恢复。
"""

import json
from typing import Any

from app.utils.logger import get_logger
from app.utils.redis_client import get_redis

logger = get_logger(__name__)

# 检查点 Redis key 前缀
_CHECKPOINT_PREFIX = "checkpoint:"

# 默认过期时间（7天）
_DEFAULT_TTL = 7 * 24 * 3600


class CheckpointManager:
    """
    检查点管理器。

    使用 Redis 存储任务执行进度检查点，
    支持保存、获取、清除和恢复操作。
    """

    def save_checkpoint(
        self,
        test_run_id: str,
        step: str,
        data: dict[str, Any],
    ) -> None:
        """
        保存检查点到 Redis。

        Args:
            test_run_id: 测试任务 ID。
            step: 当前执行步骤名称。
            data: 检查点数据（如已完成的用例、中间结果等）。
        """
        redis_client = get_redis()
        key = f"{_CHECKPOINT_PREFIX}{test_run_id}"

        checkpoint: dict[str, Any] = {
            "test_run_id": test_run_id,
            "step": step,
            "data": data,
            "timestamp": _get_timestamp(),
        }

        redis_client.set(
            key,
            json.dumps(checkpoint, ensure_ascii=False, default=str),
            ex=_DEFAULT_TTL,
        )

        logger.info(
            f"Checkpoint saved: test_run={test_run_id}, step={step}"
        )

    def get_checkpoint(self, test_run_id: str) -> dict[str, Any] | None:
        """
        获取最新检查点。

        Args:
            test_run_id: 测试任务 ID。

        Returns:
            检查点字典，不存在时返回 None。
        """
        redis_client = get_redis()
        key = f"{_CHECKPOINT_PREFIX}{test_run_id}"

        raw = redis_client.get(key)
        if raw is None:
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse checkpoint for {test_run_id}: {e}")
            return None

    def clear_checkpoint(self, test_run_id: str) -> None:
        """
        清除检查点。

        在任务完成后或取消时调用。

        Args:
            test_run_id: 测试任务 ID。
        """
        redis_client = get_redis()
        key = f"{_CHECKPOINT_PREFIX}{test_run_id}"

        redis_client.delete(key)
        logger.info(f"Checkpoint cleared: test_run={test_run_id}")

    def resume_from_checkpoint(self, test_run_id: str) -> str | None:
        """
        从检查点恢复，返回要恢复的步骤名。

        Args:
            test_run_id: 测试任务 ID。

        Returns:
            要恢复的步骤名称。无检查点时返回 None。
        """
        checkpoint = self.get_checkpoint(test_run_id)
        if checkpoint is None:
            logger.info(f"No checkpoint found for test_run={test_run_id}")
            return None

        step = checkpoint.get("step")
        logger.info(
            f"Resuming from checkpoint: test_run={test_run_id}, step={step}"
        )
        return step


def _get_timestamp() -> str:
    """获取当前 ISO 格式时间戳。"""
    from datetime import datetime

    return datetime.utcnow().isoformat() + "Z"
