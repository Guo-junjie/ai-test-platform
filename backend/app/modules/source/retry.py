"""
重试机制 — 指数退避装饰器

对网络类错误（GitCommandError / CalledProcessError / ConnectionError / TimeoutError）
执行指数退避重试（5s -> 10s -> 20s）。
SVN 认证失败（stderr 包含 "authentication"）不重试，直接抛出。
"""

import time
import subprocess
from functools import wraps
from typing import Any, Callable

from app.utils.logger import get_logger

logger = get_logger()

# 需要重试的异常类型
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    subprocess.CalledProcessError,
)

# 尝试导入 GitPython 异常（可能未安装）
try:
    from git.exc import GitCommandError as _GitCommandError

    RETRYABLE_EXCEPTIONS = (*RETRYABLE_EXCEPTIONS, _GitCommandError)
except ImportError:
    _GitCommandError = None


def _is_auth_error(exc: Exception) -> bool:
    """
    判断是否为认证类错误（不重试）。

    Args:
        exc: 捕获的异常。

    Returns:
        True 表示认证错误，不应重试。
    """
    error_text = ""
    if isinstance(exc, subprocess.CalledProcessError):
        error_text = (exc.stderr or "").lower()
    elif hasattr(exc, "stderr") and exc.stderr:
        error_text = str(exc.stderr).lower()
    elif hasattr(exc, "args") and exc.args:
        error_text = str(exc.args[0]).lower() if exc.args else ""

    auth_keywords = [
        "authentication",
        "authorization",
        "access denied",
        "permission denied",
        "invalid credentials",
        "authentication failed",
    ]
    return any(keyword in error_text for keyword in auth_keywords)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 5.0,
    max_delay: float = 30.0,
) -> Callable:
    """
    指数退避重试装饰器。

    重试策略：
    - 第 1 次重试：等待 base_delay 秒（默认 5s）
    - 第 2 次重试：等待 base_delay * 2 秒（默认 10s）
    - 第 3 次重试：等待 base_delay * 4 秒（默认 20s）
    - 最大延迟不超过 max_delay（默认 30s）

    认证类错误（SVN auth failure 等）不重试，立即抛出。

    Args:
        max_retries: 最大重试次数（不含首次执行），默认 3。
        base_delay: 基础延迟（秒），默认 5。
        max_delay: 最大延迟（秒），默认 30。

    Returns:
        装饰器函数。
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except RETRYABLE_EXCEPTIONS as e:
                    last_exception = e

                    # 认证类错误不重试
                    if _is_auth_error(e):
                        logger.error(
                            f"Authentication error in {func.__name__}, "
                            f"not retrying: {e}"
                        )
                        raise

                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                            f"after {delay:.0f}s delay. Error: {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"Max retries ({max_retries}) exceeded for "
                            f"{func.__name__}: {e}"
                        )

            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
