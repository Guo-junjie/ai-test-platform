"""
文件上传 API 路由

接收人工上传的代码压缩包（ZIP/TAR.GZ/TAR），保存到服务器后
通过 UploadAdapter 解压并创建快照。
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.modules.source import SourceConfig, SourceAdapterFactory, SourceType
from app.utils.logger import get_logger

logger = get_logger()

router = APIRouter()

# 上传文件保存目录
UPLOAD_DIR = Path("/app/data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 最大上传文件大小：500MB
MAX_UPLOAD_SIZE = 500 * 1024 * 1024

# 支持的文件格式
SUPPORTED_EXTENSIONS = (".zip", ".tar.gz", ".tgz", ".tar")

# 分块读取大小：1MB
CHUNK_SIZE = 1024 * 1024


@router.post("")
async def upload_code(file: UploadFile = File(...)):
    """
    上传代码压缩包。

    接收 ZIP/TAR.GZ/TGZ/TAR 格式的代码压缩包，保存到服务器后
    调用 SourceAdapterFactory.fetch_code() 解压并创建快照。

    返回标准化结果（local_path / snapshot_id / total_files）。
    """
    # 1. 校验文件类型
    filename = file.filename or "upload.zip"
    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(
            400,
            f"Unsupported file format. Supported: {SUPPORTED_EXTENSIONS}",
        )

    # 2. 分块保存文件（防止大文件 OOM）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = UPLOAD_DIR / f"{timestamp}_{filename}"
    total_size = 0

    logger.info(f"Receiving upload: {filename} -> {save_path}")

    try:
        with open(save_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    f.close()
                    save_path.unlink(missing_ok=True)
                    raise HTTPException(
                        413,
                        f"File too large. Max size: {MAX_UPLOAD_SIZE // 1024 // 1024}MB",
                    )
                f.write(chunk)
    finally:
        await file.close()

    logger.info(f"Upload saved: {save_path}, size={total_size} bytes")

    # 3. 调用 UploadAdapter 解压并创建快照
    config = SourceConfig(
        source_type=SourceType.UPLOAD,
        upload_file_path=str(save_path),
    )

    try:
        result = SourceAdapterFactory.fetch_code(config)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Upload processing failed: {e}")
        # 清理已保存的文件
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Upload processing failed: {e}")

    return JSONResponse(
        status_code=200,
        content={
            "code": 0,
            "data": {
                "status": "accepted",
                "local_path": result["local_path"],
                "snapshot_id": result.get("snapshot_id"),
                "version_id": result.get("version_id"),
                "total_files": result.get("total_files", 0),
                "source_type": "upload",
            },
            "message": "Upload processed successfully",
        },
    )
