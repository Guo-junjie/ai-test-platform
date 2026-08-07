"""
GitHub 仓库数据源适配器 — 全量 clone + 增量 pull

特性：
- 全量 clone：Token 注入 URL 认证，支持 depth=1 浅克隆
- 增量 pull：先 fetch 再 pull，通过 git diff 获取变更文件列表
- 支持指定分支（branch）和指定 Commit（commit_sha）
- @retry_with_backoff 装饰 fetch 方法，网络错误自动重试
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import git

from app.modules.source.base import CodeSourceAdapter, SourceAdapterFactory, SourceType
from app.modules.source.retry import retry_with_backoff
from app.utils.logger import get_logger

logger = get_logger()


class GitHubAdapter(CodeSourceAdapter):
    """GitHub 仓库数据源适配器。"""

    def supports_incremental(self) -> bool:
        """GitHub 支持增量 pull。"""
        return True

    @retry_with_backoff(max_retries=3, base_delay=5, max_delay=30)
    def fetch(self, config: Any) -> dict[str, Any]:
        """
        拉取 GitHub 仓库代码。

        根据本地是否已有仓库副本和 incremental 配置，自动选择增量 pull 或全量 clone。

        Args:
            config: SourceConfig 实例，需包含 repo_url 和 github_token。

        Returns:
            标准化结果字典。
        """
        if not config.repo_url:
            raise ValueError("repo_url is required for GitHub source")

        repo_name = self._extract_repo_name(config.repo_url)
        local_path = Path(config.workspace_dir) / repo_name

        logger.info(
            f"GitHub fetch: repo={repo_name}, branch={config.branch}, "
            f"commit={config.commit_sha or 'HEAD'}, incremental={config.incremental}, "
            f"local_exists={local_path.exists()}"
        )

        if local_path.exists() and config.incremental:
            return self._incremental_pull(config, local_path)
        else:
            # 如果目录存在但不使用增量，先清理
            if local_path.exists():
                import shutil

                shutil.rmtree(str(local_path))
            return self._fresh_clone(config, local_path)

    def _fresh_clone(
        self, config: Any, local_path: Path
    ) -> dict[str, Any]:
        """
        全量克隆 GitHub 仓库。

        Args:
            config: SourceConfig 实例。
            local_path: 本地目标路径。

        Returns:
            标准化结果字典。
        """
        # Token 注入 URL
        authed_url = config.repo_url.replace(
            "https://github.com",
            f"https://{config.github_token}@github.com",
        )

        local_path.parent.mkdir(parents=True, exist_ok=True)

        # 浅克隆（depth=1）提升速度，除非指定了 commit_sha
        clone_kwargs: dict[str, Any] = {}
        if not config.commit_sha:
            clone_kwargs["depth"] = 1
        if config.branch:
            clone_kwargs["branch"] = config.branch

        logger.info(f"Cloning from {config.repo_url} to {local_path}")
        repo = git.Repo.clone_from(authed_url, str(local_path), **clone_kwargs)

        # 如果指定了 commit_sha，checkout 到对应版本
        if config.commit_sha:
            # 需要取消浅克隆限制才能 checkout 任意 commit
            if not config.branch:
                repo.git.fetch("--unshallow", origin=authed_url)
            repo.git.checkout(config.commit_sha)

        commit_sha = repo.head.commit.hexsha
        total_files = sum(1 for _ in local_path.rglob("*") if _.is_file())

        logger.info(
            f"Clone completed: commit={commit_sha[:8]}, files={total_files}"
        )

        return {
            "local_path": str(local_path),
            "version_id": commit_sha,
            "version_label": f"branch={config.branch}, commit={commit_sha[:8]}",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": [],
            "total_files": total_files,
        }

    def _incremental_pull(
        self, config: Any, local_path: Path
    ) -> dict[str, Any]:
        """
        增量 pull 已有仓库。

        Args:
            config: SourceConfig 实例。
            local_path: 已有仓库的本地路径。

        Returns:
            标准化结果字典，包含变更文件列表。
        """
        repo = git.Repo(str(local_path))
        old_sha = repo.head.commit.hexsha

        origin = repo.remotes.origin
        logger.info(f"Incremental pull: old_sha={old_sha[:8]}")

        origin.fetch()

        if config.commit_sha:
            repo.git.checkout(config.commit_sha)
        else:
            repo.git.checkout(config.branch)
            origin.pull()

        new_sha = repo.head.commit.hexsha

        # 获取变更文件列表
        changed_files: list[str] = []
        if old_sha != new_sha:
            diff = repo.git.diff("--name-only", old_sha, new_sha)
            changed_files = diff.split("\n") if diff else []

        total_files = sum(1 for _ in local_path.rglob("*") if _.is_file())

        logger.info(
            f"Incremental pull completed: new_sha={new_sha[:8]}, "
            f"changed={len(changed_files)} files, total={total_files}"
        )

        return {
            "local_path": str(local_path),
            "version_id": new_sha,
            "version_label": f"branch={config.branch}, commit={new_sha[:8]}",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": changed_files,
            "total_files": total_files,
        }

    def _extract_repo_name(self, repo_url: str) -> str:
        """
        从 GitHub URL 提取仓库名。

        示例: https://github.com/owner/repo -> owner_repo

        Args:
            repo_url: GitHub 仓库 URL。

        Returns:
            仓库名（owner_repo 格式）。
        """
        parts = repo_url.rstrip("/").replace(".git", "").split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}_{parts[-1]}"
        return parts[-1]


# 注册适配器
SourceAdapterFactory.register(SourceType.GITHUB, GitHubAdapter)
