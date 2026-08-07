"""
Loguru 日志配置 — 统一日志格式、文件轮转、级别管理

提供：
- setup_logger(): 初始化日志配置（应在应用启动时调用）
- get_logger(name=None): 获取 logger 实例（loguru.logger 的别名）；name 参数可选，仅用于兼容现有调用

日志特性：
- 控制台输出：彩色格式，DEBUG 级别（开发）/ INFO 级别（生产）
- 文件输出：JSON 格式，每日轮转，保留 30 天
- 异常追踪：自动捕获未处理异常并记录
"""

import sys
import os
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings


# ==================== 日志目录 ====================

_LOG_DIR = Path(os.getenv("LOG_DIR", "/app/data/logs"))
_LOG_DIR.mkdir(parents=True, exist_ok=True)


# ==================== 日志格式 ====================

CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} | "
    "{message}"
)

JSON_FORMAT = (
    '{{"timestamp":"{time:YYYY-MM-DDTHH:mm:ss.SSSZ}",'
    '"level":"{level}",'
    '"logger":"{name}",'
    '"function":"{function}",'
    '"line":{line},'
    '"message":"{message}"}}'
)


# ==================== 初始化 ====================

_initialized: bool = False


def setup_logger() -> None:
    """
    初始化 Loguru 日志配置。

    - 移除默认 handler
    - 添加控制台 handler（彩色）
    - 添加文件 handler（普通日志 + 错误日志分离）
    - 配置异常拦截

    应在应用启动时（main.py 的 lifespan 中）调用一次。
    """
    global _initialized
    if _initialized:
        return

    # 移除默认 handler
    logger.remove()

    # 日志级别：开发环境 DEBUG，生产环境 INFO
    log_level = "DEBUG" if settings.APP_DEBUG else "INFO"

    # ==================== 控制台输出 ====================
    logger.add(
        sys.stdout,
        format=CONSOLE_FORMAT,
        level=log_level,
        colorize=True,
        backtrace=True,
        diagnose=settings.APP_DEBUG,
    )

    # ==================== 文件输出（全部日志） ====================
    logger.add(
        str(_LOG_DIR / "app.log"),
        format=FILE_FORMAT,
        level=log_level,
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",  # 保留 30 天
        compression="zip",  # 压缩旧日志
        encoding="utf-8",
        backtrace=True,
        diagnose=settings.APP_DEBUG,
    )

    # ==================== 文件输出（错误日志单独分离） ====================
    logger.add(
        str(_LOG_DIR / "error.log"),
        format=FILE_FORMAT,
        level="ERROR",
        rotation="00:00",
        retention="90 days",  # 错误日志保留 90 天
        compression="zip",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,  # 错误日志始终显示完整堆栈
    )

    # ==================== JSON 格式日志（供日志采集系统） ====================
    logger.add(
        str(_LOG_DIR / "app.json.log"),
        format=JSON_FORMAT,
        level="INFO",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        serialize=False,
    )

    _initialized = True
    logger.info(
        f"Logger initialized | env={settings.APP_ENV} | level={log_level} | "
        f"debug={settings.APP_DEBUG}"
    )


def get_logger(name: str | None = None) -> Any:
    """
    获取 logger 实例。

    Args:
        name: 可选参数，仅用于兼容现有调用点（如 get_logger(__name__)）。
            真实模块名由 loguru 内置的 {name} 字段自动采集，无需手动 bind，因此此处忽略该参数。

    Returns:
        loguru.logger 实例。
    """
    return logger


# ==================== 异常拦截 ====================

def _log_exception(exc_type: type, exc_value: BaseException, exc_traceback: Any) -> None:
    """全局异常拦截器 — 将未捕获异常记录到日志。"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.opt(exception=(exc_type, exc_value, exc_traceback)).error(
        f"Uncaught exception: {exc_value}"
    )


# 安装全局异常拦截
sys.excepthook = _log_exception
