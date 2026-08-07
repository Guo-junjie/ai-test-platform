"""
代码数据源适配器基类与工厂

定义统一的数据源接入接口，支持 GitHub / SVN / 人工上传三种类型。
通过工厂模式统一调度，新增数据源只需实现 CodeSourceAdapter 并注册。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Type

from app.utils.logger import get_logger

logger = get_logger()


class SourceType(Enum):
    """数据源类型枚举"""

    GITHUB = "github"
    SVN = "svn"
    UPLOAD = "upload"


@dataclass
class SourceConfig:
    """
    数据源配置 — 统一描述三种数据源的拉取参数。

    Attributes:
        source_type: 数据源类型（github / svn / upload）。
        github_token: GitHub Personal Access Token。
        repo_url: GitHub 仓库 URL（如 https://github.com/owner/repo）。
        branch: Git 分支名，默认 main。
        commit_sha: 指定 Git commit SHA（可选，用于精确版本拉取）。
        svn_url: SVN 仓库 URL。
        svn_username: SVN 认证用户名。
        svn_password: SVN 认证密码。
        svn_revision: SVN 修订版本号（可选，用于指定版本检出）。
        upload_file_path: 上传文件在服务器上的本地路径。
        workspace_dir: 代码拉取/解压的工作目录，默认 /app/data/repos。
        incremental: 是否启用增量更新模式，默认 True。
    """

    source_type: SourceType

    # GitHub
    github_token: str | None = None
    repo_url: str | None = None
    branch: str = "main"
    commit_sha: str | None = None

    # SVN
    svn_url: str | None = None
    svn_username: str | None = None
    svn_password: str | None = None
    svn_revision: str | None = None

    # Upload
    upload_file_path: str | None = None

    # 通用
    workspace_dir: str = "/app/data/repos"
    incremental: bool = True


class CodeSourceAdapter(ABC):
    """
    代码数据源适配器抽象基类。

    所有具体适配器（GitHubAdapter / SVNAdapter / UploadAdapter）必须实现
    fetch() 和 supports_incremental() 两个方法。
    """

    @abstractmethod
    def fetch(self, config: SourceConfig) -> dict[str, Any]:
        """
        拉取/接收代码，返回标准化结果。

        Args:
            config: 数据源配置。

        Returns:
            包含以下 key 的字典：
                - local_path: 代码在服务器上的本地路径
                - version_id: 版本标识（Git SHA / SVN Revision / upload hash）
                - version_label: 人类可读的版本描述
                - fetch_time: 拉取时间（ISO 8601）
                - files_changed: 变更文件列表（增量模式）
                - total_files: 总文件数
        """
        ...

    @abstractmethod
    def supports_incremental(self) -> bool:
        """是否支持增量更新。"""
        ...


class SourceAdapterFactory:
    """
    数据源适配器工厂 — 统一入口。

    通过 register() 注册适配器，通过 fetch_code() 统一调度。
    fetch_code() 在适配器拉取完成后自动调用 SnapshotManager 创建快照。
    """

    _adapters: dict[SourceType, Type[CodeSourceAdapter]] = {}

    @classmethod
    def register(
        cls, source_type: SourceType, adapter_class: Type[CodeSourceAdapter]
    ) -> None:
        """注册适配器到工厂。"""
        cls._adapters[source_type] = adapter_class
        logger.info(
            f"Source adapter registered: {source_type.value} -> {adapter_class.__name__}"
        )

    @classmethod
    def get_adapter(cls, source_type: SourceType) -> CodeSourceAdapter:
        """
        获取指定类型的适配器实例。

        Args:
            source_type: 数据源类型。

        Returns:
            适配器实例。

        Raises:
            ValueError: 未注册的适配器类型。
        """
        adapter_class = cls._adapters.get(source_type)
        if adapter_class is None:
            raise ValueError(
                f"No adapter registered for source type: {source_type.value}. "
                f"Registered types: {[t.value for t in cls._adapters]}"
            )
        return adapter_class()

    @classmethod
    def fetch_code(cls, config: SourceConfig) -> dict[str, Any]:
        """
        统一代码拉取入口 — 调用适配器拉取代码并创建快照。

        流程：
        1. 根据 source_type 获取适配器
        2. 调用 adapter.fetch() 拉取代码
        3. 调用 SnapshotManager.create() 创建快照上传到 MinIO
        4. 返回包含 snapshot_id 的标准化结果

        快照创建失败不阻断主流程（仅 log warning）。

        Args:
            config: 数据源配置。

        Returns:
            标准化结果字典，包含 local_path / version_id / snapshot_id /
            version_label / fetch_time / files_changed / total_files / source_type。
        """
        logger.info(
            f"Fetching code from source: {config.source_type.value}, "
            f"incremental={config.incremental}"
        )

        # 1. 获取适配器并拉取代码
        adapter = cls.get_adapter(config.source_type)
        result = adapter.fetch(config)

        # 补充 source_type 字段
        result["source_type"] = config.source_type.value

        # 2. 创建快照（失败不阻断主流程）
        try:
            from app.modules.source.snapshot import SnapshotManager

            snapshot_id = SnapshotManager.create(
                local_path=result["local_path"],
                version_id=result["version_id"],
            )
            result["snapshot_id"] = snapshot_id
            logger.info(f"Snapshot created: {snapshot_id}")
        except Exception as e:
            logger.warning(
                f"Snapshot creation failed (non-blocking): {e}. "
                f"Code is still available at {result['local_path']}"
            )
            result["snapshot_id"] = None

        logger.info(
            f"Code fetch completed: {config.source_type.value}, "
            f"version={result.get('version_id')}, "
            f"files={result.get('total_files')}, "
            f"snapshot={result.get('snapshot_id')}"
        )

        return result
