"""
人工上传代码适配器 — ZIP/TAR.GZ 解压

特性：
- 支持 .zip / .tar.gz / .tgz / .tar 格式
- 安全检查：防止 zip slip 和 tar 路径穿越攻击
- _flatten_if_needed()：解压后如果只有一层子目录，自动提升内容
- 不支持增量更新
- 解压后删除临时压缩包
"""

import hashlib
import shutil
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.modules.source.base import CodeSourceAdapter, SourceAdapterFactory, SourceType
from app.utils.logger import get_logger

logger = get_logger()


class UploadAdapter(CodeSourceAdapter):
    """人工上传代码文件适配器。"""

    SUPPORTED_FORMATS = {".zip", ".tar.gz", ".tgz", ".tar"}

    def supports_incremental(self) -> bool:
        """上传模式不支持增量更新。"""
        return False

    def fetch(self, config: Any) -> dict[str, Any]:
        """
        解压上传的代码压缩包到工作目录。

        Args:
            config: SourceConfig 实例，需包含 upload_file_path。

        Returns:
            标准化结果字典。

        Raises:
            FileNotFoundError: 上传文件不存在。
            ValueError: 不支持的文件格式。
        """
        upload_path = Path(config.upload_file_path)

        # 1. 格式校验
        if not upload_path.exists():
            raise FileNotFoundError(f"Upload file not found: {upload_path}")

        ext = self._get_extension(upload_path.name)
        if ext not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format: {ext}. Supported: {self.SUPPORTED_FORMATS}"
            )

        # 2. 生成唯一目录名
        file_hash = hashlib.md5(upload_path.read_bytes()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = upload_path.stem.replace(".tar", "")
        local_path = (
            Path(config.workspace_dir)
            / f"upload_{project_name}_{timestamp}_{file_hash}"
        )

        logger.info(
            f"Upload extract: file={upload_path.name}, format={ext}, "
            f"hash={file_hash}, target={local_path}"
        )

        # 3. 解压
        local_path.mkdir(parents=True, exist_ok=True)

        if ext == ".zip":
            self._extract_zip(upload_path, local_path)
        elif ext in (".tar.gz", ".tgz"):
            self._extract_tar(upload_path, local_path, mode="r:gz")
        elif ext == ".tar":
            self._extract_tar(upload_path, local_path, mode="r:")

        # 4. 检查是否有一层多余包装目录
        local_path = self._flatten_if_needed(local_path)

        # 5. 清理上传的临时文件
        upload_path.unlink(missing_ok=True)

        total_files = sum(1 for _ in local_path.rglob("*") if _.is_file())

        logger.info(
            f"Upload extract completed: files={total_files}, path={local_path}"
        )

        return {
            "local_path": str(local_path),
            "version_id": file_hash,
            "version_label": f"upload: {upload_path.name} (md5={file_hash})",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": [],
            "total_files": total_files,
        }

    def _extract_zip(self, zip_path: Path, target: Path) -> None:
        """
        安全解压 ZIP 文件，防止 zip slip 攻击。

        Args:
            zip_path: ZIP 文件路径。
            target: 解压目标目录。

        Raises:
            ValueError: 检测到不安全的 zip 条目。
        """
        target_resolved = str(target.resolve())
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 安全检查：防止 zip slip 攻击
            for member in zf.namelist():
                member_path = (target / member).resolve()
                if not str(member_path).startswith(target_resolved):
                    raise ValueError(f"Unsafe zip entry (path traversal): {member}")
            zf.extractall(target)

    def _extract_tar(self, tar_path: Path, target: Path, mode: str) -> None:
        """
        安全解压 TAR 文件，防止路径穿越。

        Args:
            tar_path: TAR 文件路径。
            target: 解压目标目录。
            mode: tarfile 打开模式（r:gz / r:）。

        Raises:
            ValueError: 检测到不安全的 tar 条目。
        """
        target_resolved = str(target.resolve())
        with tarfile.open(tar_path, mode) as tf:
            # 安全检查：防止路径穿越
            for member in tf.getmembers():
                member_path = (target / member.name).resolve()
                if not str(member_path).startswith(target_resolved):
                    raise ValueError(f"Unsafe tar entry (path traversal): {member.name}")
            tf.extractall(target)

    def _flatten_if_needed(self, path: Path) -> Path:
        """
        如果解压后只有一个子目录，则将其内容提升到当前目录。

        某些压缩包内有一层包装目录（如 repo-name/src/...），
        提升后直接是 src/...，方便后续解析。

        Args:
            path: 解压后的目录路径。

        Returns:
            调整后的目录路径（可能是原路径或提升后的路径）。
        """
        children = [c for c in path.iterdir() if not c.name.startswith(".")]
        if len(children) == 1 and children[0].is_dir():
            sole_dir = children[0]
            logger.info(f"Flattening single wrapper directory: {sole_dir.name}")
            for item in sole_dir.iterdir():
                shutil.move(str(item), str(path / item.name))
            sole_dir.rmdir()
        return path

    def _get_extension(self, filename: str) -> str:
        """
        获取文件扩展名（支持复合扩展名如 .tar.gz）。

        Args:
            filename: 文件名。

        Returns:
            小写扩展名字符串。
        """
        lower = filename.lower()
        for ext in [".tar.gz", ".tgz", ".zip", ".tar"]:
            if lower.endswith(ext):
                return ext
        return Path(lower).suffix


# 注册适配器
SourceAdapterFactory.register(SourceType.UPLOAD, UploadAdapter)
