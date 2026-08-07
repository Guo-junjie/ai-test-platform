"""
代码数据源模块 — GitHub / SVN / 人工上传适配器

导入此包时自动注册所有适配器到 SourceAdapterFactory。
"""

from app.modules.source.base import (
    CodeSourceAdapter,
    SourceConfig,
    SourceAdapterFactory,
    SourceType,
)
from app.modules.source.github_adapter import GitHubAdapter
from app.modules.source.svn_adapter import SVNAdapter
from app.modules.source.upload_adapter import UploadAdapter
from app.modules.source.snapshot import SnapshotManager
from app.modules.source.retry import retry_with_backoff

# 各适配器文件末尾已调用 SourceAdapterFactory.register()，
# 此处导入确保注册逻辑被执行
__all__ = [
    "SourceType",
    "SourceConfig",
    "CodeSourceAdapter",
    "SourceAdapterFactory",
    "GitHubAdapter",
    "SVNAdapter",
    "UploadAdapter",
    "SnapshotManager",
    "retry_with_backoff",
]
