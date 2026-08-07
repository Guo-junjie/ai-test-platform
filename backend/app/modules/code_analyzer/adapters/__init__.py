"""
接口提取适配器注册中心

定义 APIExtractorAdapter 抽象基类和适配器注册/获取机制。
各技术栈适配器通过 @register_adapter 装饰器自动注册。
"""

from abc import ABC, abstractmethod
from typing import Any


class APIExtractorAdapter(ABC):
    """
    技术栈接口提取适配器基类。

    所有具体适配器（JavaSpringAdapter / PythonFastAPIAdapter 等）
    必须实现 extract_apis() 方法，返回标准化的接口定义列表。
    """

    @abstractmethod
    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        提取项目中所有 API 接口定义。

        Args:
            project_path: 项目根目录路径。

        Returns:
            接口定义字典列表，每个字典包含以下字段：
                - path: 接口路径（如 /api/users/{id}）
                - http_method: HTTP 方法（GET / POST / PUT / DELETE / PATCH）
                - params: 参数列表 [{name, location, type, required}]
                - return_type: 返回类型描述
                - method_name: 处理函数/方法名
                - file: 源文件相对路径
                - line_number: 行号
                - auth_required: 是否需要认证
                - description: 接口描述
        """
        ...


# ==================== 适配器注册中心 ====================

_ADAPTERS: dict[str, type[APIExtractorAdapter]] = {}


def register_adapter(stack_name: str):
    """
    装饰器：注册适配器到注册中心。

    用法：
        @register_adapter("python_fastapi")
        class PythonFastAPIAdapter(APIExtractorAdapter):
            ...

    Args:
        stack_name: 技术栈名称（与 STACK_SIGNATURES 的 key 一致）。

    Returns:
        类装饰器。
    """

    def decorator(cls: type[APIExtractorAdapter]) -> type[APIExtractorAdapter]:
        _ADAPTERS[stack_name] = cls
        return cls

    return decorator


def get_adapter(stack_name: str) -> APIExtractorAdapter | None:
    """
    获取指定技术栈的适配器实例。

    Args:
        stack_name: 技术栈名称。

    Returns:
        适配器实例。未注册时返回 None。
    """
    adapter_class = _ADAPTERS.get(stack_name)
    if adapter_class is None:
        return None
    return adapter_class()


def list_registered_adapters() -> list[str]:
    """返回已注册的适配器名称列表。"""
    return list(_ADAPTERS.keys())
