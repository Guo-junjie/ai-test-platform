"""
环境适配器 — 根据技术栈自动启动被测服务

每个适配器使用 Docker 构建镜像并启动容器。
Docker 不可用时 fallback 到 localhost:PORT。

能力11 集成点：当 coverage=True（由 engine 在 AUTO_COVERAGE=1 时传入）时，
根据技术栈把覆盖率探针注入启动命令（Java→JaCoCo javaagent；Python→coverage run），
并挂载 /coverage 卷；容器 id 暂存于 self._coverage_meta，供 pipeline 测试后自动采集。
任意环节失败都安全降级为"无探针启动"，不影响测试。
"""

import os
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from app.modules.coverage.collector import override_command_for_coverage
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 服务就绪检查的默认超时时间（秒）
_DEFAULT_READY_TIMEOUT = 120
# 轮询间隔（秒）
_POLL_INTERVAL = 2

# 自动覆盖率总开关（默认关闭；worker 容器需挂载 Docker socket 且 SUT 镜像内置探针才生效）
AUTO_COVERAGE = os.getenv("AUTO_COVERAGE", "0") == "1"


class EnvironmentAdapter(ABC):
    """
    环境适配器基类。

    负责根据代码仓库的技术栈启动被测服务，
    并等待服务就绪后返回服务 URL。
    """

    # 子类填充
    image_tag: str = "test-generic:latest"
    port: int = 8000
    language: str = "unknown"
    coverage_tool: str = "cobertura"

    # 覆盖率采集暂存（仅 coverage=True 时填充）
    _container_id: Optional[str] = None
    _coverage_meta: Optional[dict] = None

    @abstractmethod
    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        ...

    def _build_and_run(
        self, repo_path: str, image_tag: str, port: int, coverage: bool
    ) -> str:
        """构建镜像并启动容器；coverage=True 时注入探针并挂载 /coverage。"""
        try:
            import docker

            client = docker.from_env()
            logger.info(f"Building Docker image for {image_tag}: {repo_path}")
            client.images.build(path=repo_path, tag=image_tag, rm=True)

            run_kwargs: dict[str, Any] = {
                # 宿主端口随机分配：固定端口与平台自身（backend 8000 等）冲突，
                # 实测 SUT 起不来 → fallback localhost → 全部用例打到平台自己
                "ports": {f"{port}/tcp": None},
                "detach": True,
                # auto_remove=False：覆盖率采集需要从「已停止的容器」拷出 XML
                # （SIGINT 优雅退出后 coverage.xml 在容器内生成）。collect_and_store
                # 拷完后显式 remove；无覆盖率路径的容器由 collect 兜底清理
                "auto_remove": False,
            }
            command = None
            if coverage:
                try:
                    img = client.images.get(image_tag)
                    cmd = (img.attrs.get("Config", {}) or {}).get("Cmd") or []
                    new_cmd = override_command_for_coverage(cmd, self.language, self.coverage_tool)
                    if new_cmd:
                        command = ["sh", "-c", "mkdir -p /coverage && " + " ".join(new_cmd)]
                        run_kwargs["volumes"] = {
                            f"coverage_data_{image_tag.replace(':', '_')}": {
                                "bind": "/coverage",
                                "mode": "rw",
                            }
                        }
                        logger.info(f"[coverage] instrumented launch for {image_tag}: {new_cmd}")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[coverage] cmd override failed ({e}); launch without probe")

            if command:
                run_kwargs["command"] = command

            container = client.containers.run(image_tag, **run_kwargs)
            # 从实际端口映射推导 service_url（host.docker.internal 由 compose
            # extra_hosts: host-gateway 提供，worker 容器内可直达宿主映射端口；
            # localhost 在 worker 容器内指向 worker 自己，SUT 不可达）
            # 【必须 reload】run() 返回对象的 attrs 里 NetworkSettings.Ports
            # 可能尚未填充（实测随机端口映射读不到 → 回退原端口 → 连接拒绝）
            try:
                container.reload()
            except Exception:  # noqa: BLE001
                pass
            host_port = port
            try:
                binding = (
                    container.attrs.get("NetworkSettings", {})
                    .get("Ports", {})
                    .get(f"{port}/tcp")
                )
                if binding and binding[0].get("HostPort"):
                    host_port = int(binding[0]["HostPort"])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"read host port mapping failed: {e}")
            service_url_final = f"http://host.docker.internal:{host_port}"
            logger.info(f"SUT service_url: {service_url_final}")
            if coverage and command:
                self._container_id = container.id
                self._coverage_meta = {
                    "container_id": container.id,
                    "tool": self.coverage_tool,
                    "language": self.language,
                }
                logger.info(f"[coverage] SUT launched with probe; container={container.id}")
            return service_url_final
        except Exception as e:
            logger.warning(
                f"Docker startup failed for {image_tag}: {e}. "
                f"Falling back to localhost:{port}"
            )
        return f"http://localhost:{port}"

    def wait_for_ready(
        self, url: str, timeout: int = _DEFAULT_READY_TIMEOUT
    ) -> bool:
        """轮询等待服务就绪（访问 /health）。"""
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

    image_tag = "test-spring-boot:latest"
    port = 8080
    language = "java"
    coverage_tool = "jacoco"

    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        return self._build_and_run(repo_path, self.image_tag, self.port, coverage)


class PythonFlaskAdapter(EnvironmentAdapter):
    """Python Flask 环境适配器。"""

    image_tag = "test-flask:latest"
    port = 5000
    language = "python"
    coverage_tool = "coverage.py"

    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        return self._build_and_run(repo_path, self.image_tag, self.port, coverage)


class PythonFastAPIAdapter(EnvironmentAdapter):
    """Python FastAPI 环境适配器。"""

    image_tag = "test-fastapi:latest"
    port = 8000
    language = "python"
    coverage_tool = "coverage.py"

    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        return self._build_and_run(repo_path, self.image_tag, self.port, coverage)


class PythonDjangoAdapter(EnvironmentAdapter):
    """Python Django 环境适配器。"""

    image_tag = "test-django:latest"
    port = 8000
    language = "python"
    coverage_tool = "coverage.py"

    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        return self._build_and_run(repo_path, self.image_tag, self.port, coverage)


class GoGinAdapter(EnvironmentAdapter):
    """Go Gin 环境适配器。"""

    image_tag = "test-gin:latest"
    port = 8080
    language = "go"
    coverage_tool = "cobertura"

    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        return self._build_and_run(repo_path, self.image_tag, self.port, coverage)


class NodeExpressAdapter(EnvironmentAdapter):
    """Node.js Express 环境适配器。"""

    image_tag = "test-express:latest"
    port = 3000
    language = "javascript"
    coverage_tool = "istanbul"

    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        return self._build_and_run(repo_path, self.image_tag, self.port, coverage)


class NodeNestJSAdapter(EnvironmentAdapter):
    """Node.js NestJS 环境适配器。"""

    image_tag = "test-nestjs:latest"
    port = 3000
    language = "javascript"
    coverage_tool = "istanbul"

    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        return self._build_and_run(repo_path, self.image_tag, self.port, coverage)


class PhpLaravelAdapter(EnvironmentAdapter):
    """PHP Laravel 环境适配器。"""

    image_tag = "test-laravel:latest"
    port = 8000
    language = "php"
    coverage_tool = "cobertura"

    def start_service(self, repo_path: str, coverage: bool = False) -> str:
        return self._build_and_run(repo_path, self.image_tag, self.port, coverage)


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
        adapter_class = cls.ADAPTERS.get(stack)
        if adapter_class is None:
            logger.warning(
                f"Unknown stack: {stack}, using PythonFastAPIAdapter as default"
            )
            adapter_class = PythonFastAPIAdapter
        return adapter_class()
