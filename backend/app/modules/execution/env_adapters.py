"""
环境适配器 — 根据技术栈自动启动被测服务

每个适配器使用 Docker 构建镜像并启动容器。
Docker 不可用时 fallback 到 localhost:8000。
"""

import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 服务就绪检查的默认超时时间（秒）
_DEFAULT_READY_TIMEOUT = 120
# 轮询间隔（秒）
_POLL_INTERVAL = 2


class EnvironmentAdapter(ABC):
    """
    环境适配器基类。

    负责根据代码仓库的技术栈启动被测服务，
    并等待服务就绪后返回服务 URL。
    """

    @abstractmethod
    def start_service(self, repo_path: str) -> str:
        """
        启动被测服务。

        Args:
            repo_path: 代码仓库本地路径。

        Returns:
            服务 URL（如 http://localhost:8080）。
        """
        ...

    def wait_for_ready(
        self, url: str, timeout: int = _DEFAULT_READY_TIMEOUT
    ) -> bool:
        """
        轮询等待服务就绪。

        通过访问 /health 端点判断服务是否启动完成。

        Args:
            url: 服务基础 URL。
            timeout: 超时时间（秒）。

        Returns:
            True 表示服务已就绪，False 表示超时。
        """
        health_url = f"{url.rstrip('/')}/health"
        logger.info(f"Waiting for service ready: {health_url} (timeout={timeout}s)")

        start = time.time()
        while time.time() - start < timeout:
            try:
                response = httpx.get(health_url, timeout=5.0)
                if response.status_code < 500:
                    logger.info(f"Service is ready: {health_url}")
                    return True
            except Exception:
                pass
            time.sleep(_POLL_INTERVAL)

        logger.warning(f"Service not ready after {timeout}s: {health_url}")
        return False


# ==================== 具体适配器 ====================


class JavaSpringAdapter(EnvironmentAdapter):
    """Java Spring Boot 环境适配器。"""

    def start_service(self, repo_path: str) -> str:
        port = 8080
        try:
            import docker

            client = docker.from_env()
            image_tag = "test-spring-boot:latest"
            logger.info(f"Building Docker image for Java Spring Boot: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)
            client.containers.run(
                image_tag,
                ports={f"{port}/tcp": port},
                detach=True,
                auto_remove=True,
            )
            logger.info(f"Spring Boot container started on port {port}")
        except Exception as e:
            logger.warning(
                f"Docker startup failed for Spring Boot: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"


class PythonFlaskAdapter(EnvironmentAdapter):
    """Python Flask 环境适配器。"""

    def start_service(self, repo_path: str) -> str:
        port = 5000
        try:
            import docker

            client = docker.from_env()
            image_tag = "test-flask:latest"
            logger.info(f"Building Docker image for Flask: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)
            client.containers.run(
                image_tag,
                ports={f"{port}/tcp": port},
                detach=True,
                auto_remove=True,
            )
            logger.info(f"Flask container started on port {port}")
        except Exception as e:
            logger.warning(
                f"Docker startup failed for Flask: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"


class PythonFastAPIAdapter(EnvironmentAdapter):
    """Python FastAPI 环境适配器。"""

    def start_service(self, repo_path: str) -> str:
        port = 8000
        try:
            import docker

            client = docker.from_env()
            image_tag = "test-fastapi:latest"
            logger.info(f"Building Docker image for FastAPI: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)
            client.containers.run(
                image_tag,
                ports={f"{port}/tcp": port},
                detach=True,
                auto_remove=True,
            )
            logger.info(f"FastAPI container started on port {port}")
        except Exception as e:
            logger.warning(
                f"Docker startup failed for FastAPI: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"


class PythonDjangoAdapter(EnvironmentAdapter):
    """Python Django 环境适配器。"""

    def start_service(self, repo_path: str) -> str:
        port = 8000
        try:
            import docker

            client = docker.from_env()
            image_tag = "test-django:latest"
            logger.info(f"Building Docker image for Django: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)
            client.containers.run(
                image_tag,
                ports={f"{port}/tcp": port},
                detach=True,
                auto_remove=True,
            )
            logger.info(f"Django container started on port {port}")
        except Exception as e:
            logger.warning(
                f"Docker startup failed for Django: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"


class GoGinAdapter(EnvironmentAdapter):
    """Go Gin 环境适配器。"""

    def start_service(self, repo_path: str) -> str:
        port = 8080
        try:
            import docker

            client = docker.from_env()
            image_tag = "test-gin:latest"
            logger.info(f"Building Docker image for Go Gin: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)
            client.containers.run(
                image_tag,
                ports={f"{port}/tcp": port},
                detach=True,
                auto_remove=True,
            )
            logger.info(f"Gin container started on port {port}")
        except Exception as e:
            logger.warning(
                f"Docker startup failed for Gin: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"


class NodeExpressAdapter(EnvironmentAdapter):
    """Node.js Express 环境适配器。"""

    def start_service(self, repo_path: str) -> str:
        port = 3000
        try:
            import docker

            client = docker.from_env()
            image_tag = "test-express:latest"
            logger.info(f"Building Docker image for Express: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)
            client.containers.run(
                image_tag,
                ports={f"{port}/tcp": port},
                detach=True,
                auto_remove=True,
            )
            logger.info(f"Express container started on port {port}")
        except Exception as e:
            logger.warning(
                f"Docker startup failed for Express: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"


class NodeNestJSAdapter(EnvironmentAdapter):
    """Node.js NestJS 环境适配器。"""

    def start_service(self, repo_path: str) -> str:
        port = 3000
        try:
            import docker

            client = docker.from_env()
            image_tag = "test-nestjs:latest"
            logger.info(f"Building Docker image for NestJS: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)
            client.containers.run(
                image_tag,
                ports={f"{port}/tcp": port},
                detach=True,
                auto_remove=True,
            )
            logger.info(f"NestJS container started on port {port}")
        except Exception as e:
            logger.warning(
                f"Docker startup failed for NestJS: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"


class PhpLaravelAdapter(EnvironmentAdapter):
    """PHP Laravel 环境适配器。"""

    def start_service(self, repo_path: str) -> str:
        port = 8000
        try:
            import docker

            client = docker.from_env()
            image_tag = "test-laravel:latest"
            logger.info(f"Building Docker image for Laravel: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)
            client.containers.run(
                image_tag,
                ports={f"{port}/tcp": port},
                detach=True,
                auto_remove=True,
            )
            logger.info(f"Laravel container started on port {port}")
        except Exception as e:
            logger.warning(
                f"Docker startup failed for Laravel: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"


# ==================== 工厂 ====================


class EnvironmentAdapterFactory:
    """环境适配器工厂。"""

    ADAPTERS: dict[str, type[EnvironmentAdapter]] = {
        "java_spring": JavaSpringAdapter,
        "python_flask": PythonFlaskAdapter,
        "python_fastapi": PythonFastAPIAdapter,
        "python_django": PythonDjangoAdapter,
        "go_gin": GoGinAdapter,
        "node_express": NodeExpressAdapter,
        "node_nestjs": NodeNestJSAdapter,
        "php_laravel": PhpLaravelAdapter,
    }

    @classmethod
    def get_adapter(cls, stack: str) -> EnvironmentAdapter:
        """
        获取指定技术栈的环境适配器。

        Args:
            stack: 技术栈名称。

        Returns:
            环境适配器实例。未知技术栈返回 FastAPI 适配器作为默认。
        """
        adapter_class = cls.ADAPTERS.get(stack)
        if adapter_class is None:
            logger.warning(
                f"Unknown stack: {stack}, using PythonFastAPIAdapter as default"
            )
            adapter_class = PythonFastAPIAdapter
        return adapter_class()
