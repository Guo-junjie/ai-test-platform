"""
SVN 仓库数据源适配器 — 全量 checkout + 增量 update

特性：
- 全量 checkout：通过 svn checkout 命令，支持指定修订版本
- 增量 update：通过 svn update 命令，支持版本间变更文件对比
- 认证参数：--non-interactive --no-auth-cache 避免交互式提示
- @retry_with_backoff 装饰 fetch 方法，网络错误自动重试（认证错误不重试）
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.modules.source.base import CodeSourceAdapter, SourceAdapterFactory, SourceType
from app.modules.source.retry import retry_with_backoff
from app.utils.logger import get_logger

logger = get_logger()


class SVNAdapter(CodeSourceAdapter):
    """SVN 仓库数据源适配器。"""

    def supports_incremental(self) -> bool:
        """SVN 支持增量 update。"""
        return True

    @retry_with_backoff(max_retries=3, base_delay=5, max_delay=30)
    def fetch(self, config: Any) -> dict[str, Any]:
        """
        拉取 SVN 仓库代码。

        根据本地是否已有工作副本和 incremental 配置，自动选择增量 update 或全量 checkout。

        Args:
            config: SourceConfig 实例，需包含 svn_url。

        Returns:
            标准化结果字典。
        """
        if not config.svn_url:
            raise ValueError("svn_url is required for SVN source")

        repo_name = self._extract_svn_name(config.svn_url)
        local_path = Path(config.workspace_dir) / repo_name

        logger.info(
            f"SVN fetch: repo={repo_name}, revision={config.svn_revision or 'HEAD'}, "
            f"incremental={config.incremental}, local_exists={local_path.exists()}"
        )

        if local_path.exists() and config.incremental:
            return self._svn_update(config, local_path)
        else:
            # 如果目录存在但不使用增量，先清理
            if local_path.exists():
                import shutil

                shutil.rmtree(str(local_path))
            return self._svn_checkout(config, local_path)

    def _svn_checkout(
        self, config: Any, local_path: Path
    ) -> dict[str, Any]:
        """
        SVN 全量检出。

        Args:
            config: SourceConfig 实例。
            local_path: 本地目标路径。

        Returns:
            标准化结果字典。
        """
        cmd: list[str] = ["svn", "checkout", config.svn_url, str(local_path)]

        # 认证参数
        if config.svn_username and config.svn_password:
            cmd.extend(
                [
                    "--username", config.svn_username,
                    "--password", config.svn_password,
                    "--non-interactive",
                    "--no-auth-cache",
                ]
            )

        # 指定修订版本
        if config.svn_revision:
            cmd.extend(["-r", config.svn_revision])

        local_path.parent.mkdir(parents=True, exist_ok=True)
        timeout = settings.SVN_DEFAULT_TIMEOUT * 5  # checkout 超时放大 5 倍

        logger.info(f"SVN checkout: {config.svn_url} -> {local_path}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(f"SVN checkout failed: {result.stderr}")

        revision = self._get_revision(local_path)
        total_files = sum(1 for _ in local_path.rglob("*") if _.is_file())

        logger.info(
            f"SVN checkout completed: revision=r{revision}, files={total_files}"
        )

        return {
            "local_path": str(local_path),
            "version_id": f"r{revision}",
            "version_label": f"svn_url={config.svn_url}, revision=r{revision}",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": [],
            "total_files": total_files,
        }

    def _svn_update(
        self, config: Any, local_path: Path
    ) -> dict[str, Any]:
        """
        SVN 增量更新。

        Args:
            config: SourceConfig 实例。
            local_path: 已有工作副本的本地路径。

        Returns:
            标准化结果字典，包含变更文件列表。
        """
        old_revision = self._get_revision(local_path)

        cmd: list[str] = ["svn", "update", str(local_path)]
        if config.svn_username and config.svn_password:
            cmd.extend(
                [
                    "--username", config.svn_username,
                    "--password", config.svn_password,
                    "--non-interactive",
                    "--no-auth-cache",
                ]
            )
        if config.svn_revision:
            cmd.extend(["-r", config.svn_revision])

        timeout = settings.SVN_DEFAULT_TIMEOUT * 5

        logger.info(f"SVN update: {local_path}, old_revision=r{old_revision}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(f"SVN update failed: {result.stderr}")

        new_revision = self._get_revision(local_path)

        # 获取变更文件列表
        changed_files: list[str] = []
        if old_revision != new_revision:
            changed_files = self._get_changed_files(
                local_path, old_revision, new_revision
            )

        total_files = sum(1 for _ in local_path.rglob("*") if _.is_file())

        logger.info(
            f"SVN update completed: new_revision=r{new_revision}, "
            f"changed={len(changed_files)} files, total={total_files}"
        )

        return {
            "local_path": str(local_path),
            "version_id": f"r{new_revision}",
            "version_label": f"svn_url={config.svn_url}, revision=r{new_revision}",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": changed_files,
            "total_files": total_files,
        }

    def _get_revision(self, path: Path) -> str:
        """
        获取工作副本的当前修订版本号。

        Args:
            path: SVN 工作副本路径。

        Returns:
            修订版本号字符串。
        """
        result = subprocess.run(
            ["svn", "info", "--show-item", "revision", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    def _get_changed_files(
        self, path: Path, old_rev: str, new_rev: str
    ) -> list[str]:
        """
        获取两个修订版本之间的变更文件列表。

        Args:
            path: SVN 工作副本路径。
            old_rev: 旧修订版本号。
            new_rev: 新修订版本号。

        Returns:
            变更文件路径列表。
        """
        result = subprocess.run(
            [
                "svn", "diff",
                "-r", f"{old_rev}:{new_rev}",
                "--summarize",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        files: list[str] = []
        for line in result.stdout.strip().split("\n"):
            if line:
                # 格式: "M       path/to/file" / "A       path/to/file" / "D       path/to/file"
                parts = line.split(None, 1)
                if len(parts) == 2:
                    files.append(parts[1])
        return files

    def _extract_svn_name(self, svn_url: str) -> str:
        """
        从 SVN URL 提取项目名。

        示例: https://svn.example.com/svn/project -> svn_project

        Args:
            svn_url: SVN 仓库 URL。

        Returns:
            项目名（svn_ 前缀格式）。
        """
        name = svn_url.rstrip("/").split("/")[-1]
        return f"svn_{name}"


# 注册适配器
SourceAdapterFactory.register(SourceType.SVN, SVNAdapter)
