"""在部署机验证生产 Compose；仅使用虚拟值渲染，不读取真实密钥。"""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
values = {
    "BACKEND_IMAGE": "aitp-backend:validation", "FRONTEND_IMAGE": "aitp-frontend:validation",
    "POSTGRES_IMAGE": "postgres:16-alpine", "REDIS_IMAGE": "redis:7-alpine",
    "RABBITMQ_IMAGE": "rabbitmq:3.13-management-alpine", "MINIO_IMAGE": "minio/minio:validation",
    "POSTGRES_PASSWORD": "validation-password-only", "REDIS_PASSWORD": "validation-password-only",
    "RABBITMQ_PASSWORD": "validation-password-only", "MINIO_SECRET_KEY": "validation-password-only",
}
with tempfile.TemporaryDirectory(prefix="aitp-compose-validation-") as folder:
    env_path = Path(folder) / "test.env"
    env_path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    environment = {**os.environ, "PROD_ENV_FILE": str(env_path)}
    subprocess.run(["docker", "compose", "--env-file", str(env_path), "-f",
                    str(root / "docker-compose.prod.yml"), "config", "--quiet"],
                   env=environment, check=True)
print("production compose: valid")
