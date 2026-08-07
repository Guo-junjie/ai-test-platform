"""
统一接口提取器 — 根据技术栈自动选择适配器提取 API 接口

作为 StackDetector 和各适配器之间的调度层，提供统一的 extract() 入口。
"""

from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


class APIExtractor:
    """
    统一接口提取器。

    根据 StackDetector 返回的技术栈信息，自动选择对应的适配器，
    调用适配器的 extract_apis() 方法提取所有 API 接口定义。
    """

    def extract(self, project_path: str, stack_info: dict[str, Any]) -> list[dict[str, Any]]:
        """
        根据技术栈选择适配器提取所有 API 接口。

        Args:
            project_path: 项目根目录路径。
            stack_info: StackDetector.detect() 返回的技术栈信息，
                需包含 "stack" 字段。

        Returns:
            标准化接口定义列表。如果技术栈不支持或无适配器，返回空列表。
        """
        from app.modules.code_analyzer.adapters import get_adapter

        stack_name = stack_info.get("stack", "unknown")

        if stack_name == "unknown":
            logger.warning(
                f"Tech stack is unknown, cannot extract APIs. "
                f"Please check if the project has recognizable framework signatures."
            )
            return []

        adapter = get_adapter(stack_name)

        if adapter is None:
            logger.warning(
                f"No adapter registered for stack: {stack_name}. "
                f"Skipping API extraction."
            )
            return []

        logger.info(f"Extracting APIs using adapter: {stack_name}")

        try:
            apis = adapter.extract_apis(project_path)
            logger.info(
                f"Extracted {len(apis)} APIs from {stack_name} project "
                f"at {project_path}"
            )
            return apis
        except Exception as e:
            logger.error(
                f"Failed to extract APIs for stack {stack_name}: {e}",
                exc_info=True,
            )
            return []
