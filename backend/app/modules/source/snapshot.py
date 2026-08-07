"""
代码快照管理器 — 打包上传到 MinIO，支持快照恢复

每次代码拉取/上传后创建版本快照，上传到 MinIO 对象存储。
快照 ID 格式：snap_{YYYYMMDD}_{uuid8}。
快照路径：MinIO://{bucket}/snapshots/{snapshot_id}.tar.gz
"""

import tarfile
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.logger import get_logger
from app.utils.storage import download_file, upload_file

logger = get_logger()


class SnapshotManager:
    """
    代码快照管理器。

    提供快照的创建、查询和恢复功能。快照以 tar.gz 格式存储在 MinIO 中，
    用于版本回退和缓存命中（容错兜底策略 use_cached_snapshot）。
    """

    @staticmethod
    def create(local_path: str, version_id: str) -> str:
        """
        创建代码快照 — 将本地代码目录打包上传到 MinIO。

        流程：
        1. 生成 snapshot_id: snap_{YYYYMMDD}_{uuid8}
        2. 将 local_path 打包为 tar.gz 临时文件
        3. 上传到 MinIO (object_name = snapshots/{snapshot_id}.tar.gz)
        4. 清理临时文件
        5. 返回 snapshot_id

        Args:
            local_path: 代码在服务器上的本地路径。
            version_id: 版本标识（Git SHA / SVN Revision / upload hash）。

        Returns:
            snapshot_id 字符串。异常时返回 fallback ID "snap_error_{timestamp}"。
        """
        source_path = Path(local_path)
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        snapshot_id = f"snap_{timestamp}_{uuid.uuid4().hex[:8]}"
        object_name = f"snapshots/{snapshot_id}.tar.gz"

        # 创建临时 tar.gz 文件
        tmp_tar = None
        try:
            tmp_tar = tempfile.NamedTemporaryFile(
                suffix=".tar.gz", delete=False, dir="/tmp"
            )
            tmp_tar.close()  # 关闭文件句柄，交给 tarfile 使用

            logger.info(
                f"Creating snapshot: {snapshot_id} from {local_path} "
                f"(version={version_id})"
            )

            with tarfile.open(tmp_tar.name, "w:gz") as tar:
                tar.add(str(source_path), arcname=source_path.name)

            # 上传到 MinIO
            upload_file(
                local_path=tmp_tar.name,
                object_name=object_name,
            )

            logger.info(f"Snapshot uploaded to MinIO: {object_name}")
            return snapshot_id

        except Exception as e:
            logger.error(
                f"Failed to create snapshot for {local_path}: {e}. "
                f"Returning fallback ID."
            )
            return f"snap_error_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        finally:
            # 清理临时文件
            if tmp_tar and Path(tmp_tar.name).exists():
                try:
                    Path(tmp_tar.name).unlink()
                except OSError:
                    pass

    @staticmethod
    def get_snapshot_path(snapshot_id: str) -> str | None:
        """
        获取快照在 MinIO 中的对象路径。

        Args:
            snapshot_id: 快照 ID。

        Returns:
            MinIO 对象路径 (snapshots/{snapshot_id}.tar.gz)，
            如果是错误快照（snap_error_ 前缀）则返回 None。
        """
        if snapshot_id.startswith("snap_error_"):
            return None
        return f"snapshots/{snapshot_id}.tar.gz"

    @staticmethod
    def restore(snapshot_id: str, target_path: str) -> str:
        """
        从 MinIO 下载快照并解压到目标路径。

        用于容错兜底策略 use_cached_snapshot：当代码拉取失败时，
        从最近的成功快照恢复代码。

        Args:
            snapshot_id: 快照 ID。
            target_path: 解压目标目录。

        Returns:
            实际代码目录路径（解压后的子目录）。

        Raises:
            ValueError: 快照 ID 无效或不存在。
        """
        object_name = SnapshotManager.get_snapshot_path(snapshot_id)
        if object_name is None:
            raise ValueError(f"Invalid or error snapshot ID: {snapshot_id}")

        target = Path(target_path)
        target.mkdir(parents=True, exist_ok=True)

        # 下载到临时文件
        tmp_tar = tempfile.NamedTemporaryFile(
            suffix=".tar.gz", delete=False, dir="/tmp"
        )
        tmp_tar.close()

        try:
            logger.info(f"Restoring snapshot {snapshot_id} to {target_path}")
            download_file(
                object_name=object_name,
                local_path=tmp_tar.name,
            )

            # 解压
            with tarfile.open(tmp_tar.name, "r:gz") as tar:
                # 安全检查：防止路径穿越
                base = target.resolve()
                for member in tar.getmembers():
                    member_path = (target / member.name).resolve()
                    if not str(member_path).startswith(str(base)):
                        raise ValueError(f"Unsafe tar entry: {member.name}")
                tar.extractall(path=str(target))

            logger.info(f"Snapshot {snapshot_id} restored to {target_path}")
            return str(target)

        finally:
            if Path(tmp_tar.name).exists():
                try:
                    Path(tmp_tar.name).unlink()
                except OSError:
                    pass
