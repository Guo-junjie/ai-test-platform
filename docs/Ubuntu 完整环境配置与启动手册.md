# AI 测试平台 — Ubuntu 完整环境配置与启动手册

> **目标系统**: Ubuntu 22.04 LTS (Jammy) / Ubuntu 24.04 LTS (Noble)
> **项目目录**: 假设项目放置在 `/opt/ai-test-platform`
> **架构**: FastAPI 后端 + Vue 3 前端 + PostgreSQL + Redis + RabbitMQ + MinIO + Celery

---

## 目录

1. [系统准备](#1-系统准备)
2. [安装 PostgreSQL 16](#2-安装-postgresql-16)
3. [安装 Redis 7](#3-安装-redis-7)
4. [安装 RabbitMQ 3.13](#4-安装-rabbitmq-313)
5. [安装 MinIO](#5-安装-minio)
6. [安装 Python 环境](#6-安装-python-环境)
7. [安装 Node.js 环境](#7-安装-nodejs-环境)
8. [配置项目](#8-配置项目)
9. [修复已知问题](#9-修复已知问题)
10. [启动后端服务](#10-启动后端服务)
11. [启动前端服务](#11-启动前端服务)
12. [验证与访问](#12-验证与访问)
13. [生产环境建议](#13-生产环境建议)
14. [故障排查](#14-故障排查)

---

## 1. 系统准备

### 1.1 更新系统

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.2 安装基础工具

```bash
sudo apt install -y \
    curl wget git vim \
    build-essential pkg-config \
    libssl-dev libffi-dev \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libffi-dev \
    shared-mime-info \
    unzip
```

> **说明**: `libcairo2`、`libpango` 等是 WeasyPrint（PDF 报告生成）的系统级依赖，必须安装，否则后端启动时 `import weasyprint` 会报错。

### 1.3 创建项目目录

```bash
sudo mkdir -p /opt/ai-test-platform
sudo chown $USER:$USER /opt/ai-test-platform
```

### 1.4 创建数据目录

```bash
sudo mkdir -p /app/data/logs
sudo mkdir -p /app/data/repos
sudo mkdir -p /app/data/reports
sudo chown -R $USER:$USER /app/data
```

> **说明**: 项目默认 `WORKSPACE_DIR=/app/data/repos`、`REPORT_DIR=/app/data/reports`、日志目录 `/app/data/logs`。如需修改路径，请在 `.env` 文件中调整。

---

## 2. 安装 PostgreSQL 16

### 2.1 添加官方仓库并安装

```bash
# 添加 PostgreSQL 官方 APT 仓库
sudo sh -c 'echo "deb https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg

# 安装 PostgreSQL 16
sudo apt update
sudo apt install -y postgresql-16 postgresql-contrib
```

### 2.2 启动并设置开机自启

```bash
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

### 2.3 创建数据库和用户

```bash
sudo -u postgres psql << 'EOF'
-- 创建用户
CREATE USER aitp WITH PASSWORD 'aitp_secret_2026';

-- 创建数据库
CREATE DATABASE ai_test_platform OWNER aitp;

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE ai_test_platform TO aitp;

-- 切换到目标数据库，启用 UUID 扩展
\c ai_test_platform
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 授予 schema 权限
GRANT ALL ON SCHEMA public TO aitp;
EOF
```

### 2.4 验证连接

```bash
psql -h localhost -U aitp -d ai_test_platform -c "SELECT version();"
# 输入密码: aitp_secret_2026
```

### 2.5 确认 PostgreSQL 监听地址（如需远程访问）

```bash
# 编辑配置
sudo vim /etc/postgresql/16/main/postgresql.conf
# 找到 listen_addresses，改为:
#   listen_addresses = 'localhost'   # 仅本地访问（默认）
#   listen_addresses = '*'           # 允许远程访问

# 编辑客户端认证
sudo vim /etc/postgresql/16/main/pg_hba.conf
# 添加（如需远程访问）:
#   host    ai_test_platform    aitp    0.0.0.0/0    scram-sha-256

# 重启生效
sudo systemctl restart postgresql
```

---

## 3. 安装 Redis 7

### 3.1 添加官方仓库并安装

```bash
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/redis.list

sudo apt update
sudo apt install -y redis
```

### 3.2 启动并设置开机自启

```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

### 3.3 验证

```bash
redis-cli ping
# 期望输出: PONG
```

### 3.4 配置密码（可选，生产环境建议）

```bash
sudo vim /etc/redis/redis.conf
# 找到 # requirepass foobared，取消注释并修改:
#   requirepass your_redis_password

sudo systemctl restart redis-server
```

> 如果设置了 Redis 密码，请在 `.env` 中更新 `REDIS_PASSWORD`。

---

## 4. 安装 RabbitMQ 3.13

### 4.1 添加 Erlang/RabbitMQ 仓库（Team RabbitMQ 官方 apt 仓库）

> ⚠️ **重要变更说明**：旧版手册用的 `packagecloud.io/rabbitmq/erlang` 仓库在 jammy 上已失效（404 无 Release 文件）；Cloudsmith 密钥 URL 路径也不稳定。以下采用 **RabbitMQ 官方文档当前推荐** 的 Team RabbitMQ apt 仓库（`deb1/deb2.rabbitmq.com`），密钥来自 openpgp.org，已验证可用于 Ubuntu 22.04 (jammy) 与 24.04 (noble)。
>
> **另一个常见坑**：安装 Erlang 时包名必须带 `erlang-` 前缀（如 `erlang-crypto`、`erlang-ssl`），不能写裸名 `crypto` / `ssl`（那是 Erlang 内部模块名，不是 apt 包名）。

```bash
# 1) 清理之前可能生成的失效/空密钥与仓库文件
sudo rm -f /usr/share/keyrings/rabbitmq-erlang-archive-keyring.gpg \
          /usr/share/keyrings/rabbitmq-archive-keyring.gpg \
          /etc/apt/sources.list.d/rabbitmq-erlang.list \
          /etc/apt/sources.list.d/rabbitmq-server.list

# 2) 下载 Team RabbitMQ 签名密钥（指纹 0A9AF2115F4687BD29803A206B73A36E6026DFCA）
curl -1sLf "https://keys.openpgp.org/vks/v1/by-fingerprint/0A9AF2115F4687BD29803A206B73A36E6026DFCA" | sudo gpg --dearmor | sudo tee /usr/share/keyrings/com.rabbitmq.team.gpg > /dev/null

# 3) 添加仓库（Ubuntu 22.04 = jammy；24.04 请将 jammy 改为 noble）
sudo tee /etc/apt/sources.list.d/rabbitmq.list <<'EOF'
deb [arch=amd64 signed-by=/usr/share/keyrings/com.rabbitmq.team.gpg] https://deb1.rabbitmq.com/rabbitmq-erlang/ubuntu/jammy jammy main
deb [arch=amd64 signed-by=/usr/share/keyrings/com.rabbitmq.team.gpg] https://deb2.rabbitmq.com/rabbitmq-erlang/ubuntu/jammy jammy main
deb [arch=amd64 signed-by=/usr/share/keyrings/com.rabbitmq.team.gpg] https://deb1.rabbitmq.com/rabbitmq-server/ubuntu/jammy jammy main
deb [arch=amd64 signed-by=/usr/share/keyrings/com.rabbitmq.team.gpg] https://deb2.rabbitmq.com/rabbitmq-server/ubuntu/jammy jammy main
EOF

# 4) 更新
sudo apt-get update -y

# 5) 安装 Erlang（注意 erlang- 前缀）
sudo apt-get install -y erlang-base erlang-asn1 erlang-crypto erlang-eldap erlang-ftp erlang-inets erlang-mnesia erlang-os-mon erlang-parsetools erlang-public-key erlang-runtime-tools erlang-snmp erlang-ssl erlang-syntax-tools erlang-tftp erlang-tools erlang-xmerl

# 6) 安装 RabbitMQ
sudo apt-get install rabbitmq-server -y --fix-missing
```

> **备选方案（最简单，仅 Ubuntu）— Launchpad PPA**：若上面的 `deb1/deb2.rabbitmq.com` 访问不畅，可直接用官方 PPA，密钥自动处理，一条命令装好 Erlang + RabbitMQ：
> ```bash
> sudo apt-get install -y software-properties-common
> sudo add-apt-repository -y ppa:rabbitmq/rabbitmq-erlang
> sudo add-apt-repository -y ppa:rabbitmq/rabbitmq-server
> sudo apt-get update
> sudo apt-get install -y rabbitmq-server
> ```
>
> 若以上都装不上 3.13，Ubuntu 22.04 自带仓库里有 `rabbitmq-server` 3.10 版本（直接 `sudo apt-get install -y rabbitmq-server`）也可临时跑通，但部分新特性可能不可用。

### 4.2 启动并设置开机自启

```bash
sudo systemctl enable rabbitmq-server
sudo systemctl start rabbitmq-server
```

### 4.3 创建用户和配置

```bash
# 创建用户
sudo rabbitmqctl add_user aitp aitp_secret_2026

# 设置用户标签（管理员）
sudo rabbitmqctl set_user_tags aitp administrator

# 设置权限
sudo rabbitmqctl set_permissions -p / aitp ".*" ".*" ".*"

# 启用管理界面（可选，推荐）
sudo rabbitmq-plugins enable rabbitmq_management
```

### 4.4 验证

```bash
# 检查状态
sudo rabbitmqctl status

# 访问管理界面（如启用了 management 插件）
# 浏览器打开: http://<服务器IP>:15672
# 用户名: aitp  密码: aitp_secret_2026
```

### 4.5 删除默认 guest 用户（安全建议）

```bash
sudo rabbitmqctl delete_user guest
```

---

## 5. 安装 MinIO

### 5.1 下载 MinIO 二进制文件

```bash
wget https://dl.min.io/server/minio/release/linux-amd64/minio
sudo mv minio /usr/local/bin/
sudo chmod +x /usr/local/bin/minio
```

### 5.2 创建 MinIO 数据目录

```bash
sudo mkdir -p /data/minio
sudo chown -R $USER:$USER /data/minio
```

### 5.3 创建 systemd 服务

```bash
sudo tee /etc/systemd/system/minio.service << 'EOF'
[Unit]
Description=MinIO Object Storage
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
Group=YOUR_USERNAME
Environment="MINIO_ROOT_USER=aitp"
Environment="MINIO_ROOT_PASSWORD=aitp_secret_2026"
ExecStart=/usr/local/bin/minio server /data/minio --console-address ":9001"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 替换用户名
sudo sed -i "s/YOUR_USERNAME/$USER/g" /etc/systemd/system/minio.service
```

### 5.4 启动并设置开机自启

```bash
sudo systemctl daemon-reload
sudo systemctl enable minio
sudo systemctl start minio
```

### 5.5 验证

```bash
# 检查服务状态
sudo systemctl status minio

# 检查 API 端口 (9000) 和管理界面端口 (9001)
curl http://localhost:9000/minio/health/live
# 期望输出为空（HTTP 200）

# 浏览器访问管理界面:
# http://<服务器IP>:9001
# 用户名: aitp  密码: aitp_secret_2026
```

---

## 6. 安装 Python 环境

### 6.1 安装 Python 3.11+

```bash
sudo apt install -y python3 python3-dev python3-venv python3-pip
```

> Ubuntu 22.04 自带 Python 3.10，24.04 自带 Python 3.12。项目需要 Python 3.11+。
> 如果是 Ubuntu 22.04，建议添加 deadsnakes PPA 安装 Python 3.11:
> ```bash
> sudo add-apt-repository ppa:deadsnakes/ppa
> sudo apt update
> sudo apt install -y python3.11 python3.11-dev python3.11-venv
> ```

### 6.2 创建虚拟环境

```bash
cd /opt/ai-test-platform/backend

# Ubuntu 24.04 (Python 3.12)
python3 -m venv venv

# Ubuntu 22.04 + deadsnakes (Python 3.11)
# python3.11 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 升级 pip
pip install --upgrade pip setuptools wheel
```

### 6.3 安装后端依赖

```bash
# 确保在虚拟环境中
source /opt/ai-test-platform/backend/venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 如果 pysvn 安装失败（常见问题），可以先跳过:
# pip install -r requirements.txt --no-deps pysvn
# 或者安装 svn 开发库后重试:
# sudo apt install -y libsvn-dev subversion
# pip install pysvn
```

> **pysvn 说明**: `pysvn` 是 SVN 代码源管理功能所需。如果项目暂不使用 SVN，可以注释掉 `requirements.txt` 中的 `pysvn==1.9.15`，不影响其他功能。

### 6.4 安装 Docker SDK（可选）

如果项目需要使用 Docker 执行测试用例（Docker 执行模式），需要安装 Docker:

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sudo sh

# 将当前用户加入 docker 组
sudo usermod -aG docker $USER

# 需要重新登录才能生效
# 或临时使用: newgrp docker
```

---

## 7. 安装 Node.js 环境

### 7.1 安装 Node.js 20 LTS

```bash
# 使用 NodeSource 仓库
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 验证
node --version   # 期望: v20.x.x
npm --version    # 期望: 10.x.x
```

### 7.2 安装前端依赖

```bash
cd /opt/ai-test-platform/frontend
npm install
```

---

## 8. 配置项目

### 8.1 放置项目代码

将项目代码复制到 `/opt/ai-test-platform`:

```bash
# 假设代码已通过 git clone 或 scp 传输到服务器
# 最终目录结构应为:
/opt/ai-test-platform/
├── backend/
│   ├── app/
│   ├── alembic/
│   ├── alembic.ini
│   ├── requirements.txt
│   └── ...
├── frontend/
│   ├── src/
│   ├── package.json
│   ├── vite.config.ts
│   └── ...
├── docker-compose.yml
├── .env.example
└── docs/
```

### 8.2 创建 .env 文件

```bash
cd /opt/ai-test-platform
cp .env.example .env
```

编辑 `.env` 文件，**将所有服务主机改为 localhost**:

```bash
vim .env
```

完整的 `.env` 配置内容（Ubuntu 本地部署版本）:

```env
# =====================
# 数据库配置 (PostgreSQL)
# =====================
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=aitp
POSTGRES_PASSWORD=aitp_secret_2026
POSTGRES_DB=ai_test_platform

# =====================
# Redis 配置
# =====================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

# =====================
# RabbitMQ 配置
# =====================
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=aitp
RABBITMQ_PASSWORD=aitp_secret_2026

# =====================
# MinIO 配置
# =====================
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=aitp
MINIO_SECRET_KEY=aitp_secret_2026
MINIO_BUCKET=ai-test-platform
MINIO_SECURE=false

# =====================
# 应用配置
# =====================
DEBUG=true
SECRET_KEY=your-secret-key-change-this-in-production-please-make-it-long-enough
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24
ACCESS_TOKEN_EXPIRE_MINUTES=30

# =====================
# 默认管理员
# =====================
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=admin123

# =====================
# 文件存储路径
# =====================
WORKSPACE_DIR=/app/data/repos
REPORT_DIR=/app/data/reports
LOG_DIR=/app/data/logs

# =====================
# AI 模型配置 (可选，按需填写)
# =====================
OPENAI_API_KEY=
OPENAI_API_BASE=https://api.openai.com/v1
ANTHROPIC_API_KEY=

# =====================
# 端口配置
# =====================
BACKEND_PORT=8000
FRONTEND_PORT=3000
```

### 8.3 配置 Alembic 数据库迁移

确保 `alembic.ini` 中的数据库 URL 正确:

```ini
# /opt/ai-test-platform/backend/alembic.ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+psycopg2://aitp:aitp_secret_2026@localhost:5432/ai_test_platform
```

> 如果你在 `.env` 中修改了数据库密码，请同步更新 `alembic.ini`。

### 8.4 执行数据库迁移

```bash
cd /opt/ai-test-platform/backend
source venv/bin/activate

# 执行迁移
alembic upgrade head
```

> 如果遇到 `uuid-ossp` 相关错误，请确认已执行步骤 2.3 中的 `CREATE EXTENSION` 语句。

---

## 9. 修复已知问题

### 9.1 修复 logger.py 缺少 `import os`

文件 `backend/app/utils/logger.py` 第 25 行使用了 `os.getenv("LOG_DIR", ...)` 但未导入 `os` 模块。

```bash
vim /opt/ai-test-platform/backend/app/utils/logger.py
```

在文件顶部的 import 区域添加 `import os`:

```python
# 修改前:
import sys
from pathlib import Path
from typing import Any

# 修改后:
import os
import sys
from pathlib import Path
from typing import Any
```

> **替代方案**: 如果在 `.env` 中设置了 `LOG_DIR` 环境变量，且通过 `python-dotenv` 加载，也可以避免此问题。但建议直接修复代码。

### 9.2 检查 WeasyPrint 是否正常

```bash
source /opt/ai-test-platform/backend/venv/bin/activate
python -c "import weasyprint; print('WeasyPrint OK:', weasyprint.__version__)"
```

如果报错，检查系统依赖是否安装完整:

```bash
sudo apt install -y \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libffi-dev \
    shared-mime-info fonts-liberation
```

---

## 10. 启动后端服务

### 10.1 加载环境变量

确保每次启动前都加载 `.env`:

```bash
cd /opt/ai-test-platform
export $(grep -v '^#' .env | xargs)
```

> **推荐方式**: 使用 `direnv` 或在启动脚本中自动 source `.env`。

### 10.2 启动 FastAPI 后端

```bash
cd /opt/ai-test-platform/backend
source venv/bin/activate

# 加载环境变量
set -a; source /opt/ai-test-platform/.env; set +a

# 开发模式（热重载）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 生产模式（多进程，无热重载）
# uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

> 后端启动时会依次执行: 初始化日志 → 初始化数据库 → 初始化 MinIO Bucket → 加载 AI 模型配置 → 创建默认管理员账号。
> 看到类似 `Uvicorn running on http://0.0.0.0:8000` 即表示启动成功。

### 10.3 启动 Celery Worker

打开**新的终端**:

```bash
cd /opt/ai-test-platform/backend
source venv/bin/activate
set -a; source /opt/ai-test-platform/.env; set +a

celery -A app.celery_app worker --loglevel=info --concurrency=4
```

### 10.4 启动 Celery Beat（定时任务调度器）

打开**新的终端**:

```bash
cd /opt/ai-test-platform/backend
source venv/bin/activate
set -a; source /opt/ai-test-platform/.env; set +a

celery -A app.celery_app beat --loglevel=info
```

### 10.5 创建一键启动脚本（可选，推荐）

```bash
cat > /opt/ai-test-platform/start_backend.sh << 'SCRIPT'
#!/bin/bash

PROJECT_DIR="/opt/ai-test-platform"
BACKEND_DIR="$PROJECT_DIR/backend"
ENV_FILE="$PROJECT_DIR/.env"

# 加载环境变量
set -a; source "$ENV_FILE"; set +a

# 启动 FastAPI
cd "$BACKEND_DIR"
source venv/bin/activate

echo "Starting FastAPI backend..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

echo "Starting Celery Worker..."
celery -A app.celery_app worker --loglevel=info --concurrency=4 &
WORKER_PID=$!

echo "Starting Celery Beat..."
celery -A app.celery_app beat --loglevel=info &
BEAT_PID=$!

echo "All services started. PIDs: Backend=$BACKEND_PID, Worker=$WORKER_PID, Beat=$BEAT_PID"
echo "Press Ctrl+C to stop all services."

trap "kill $BACKEND_PID $WORKER_PID $BEAT_PID 2>/dev/null; exit" SIGINT SIGTERM

wait
SCRIPT

chmod +x /opt/ai-test-platform/start_backend.sh
```

使用方式:

```bash
/opt/ai-test-platform/start_backend.sh
```

---

## 11. 启动前端服务

### 11.1 开发模式

```bash
cd /opt/ai-test-platform/frontend

# 开发服务器（热重载）
npm run dev
```

> 前端开发服务器运行在 `http://localhost:3000`，`/api` 请求会自动代理到 `http://localhost:8000`。

### 11.2 生产构建

```bash
cd /opt/ai-test-platform/frontend

# 构建静态文件
npm run build

# 预览构建结果
npm run preview
```

构建产物在 `frontend/dist/` 目录，可使用 Nginx 托管。

### 11.3 Nginx 反向代理配置（生产环境推荐）

```bash
sudo apt install -y nginx

sudo tee /etc/nginx/sites-available/ai-test-platform << 'EOF'
server {
    listen 80;
    server_name _;  # 修改为你的域名或IP

    # 前端静态文件
    root /opt/ai-test-platform/frontend/dist;
    index index.html;

    # 前端路由
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket 支持（如需实时通信）
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/ai-test-platform /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

## 12. 验证与访问

### 12.1 服务端口清单

| 服务 | 端口 | 用途 |
|------|------|------|
| FastAPI 后端 | 8000 | API 服务 |
| Vite 前端 (dev) | 3000 | 开发服务器 |
| Nginx (prod) | 80 | 静态文件 + 反向代理 |
| PostgreSQL | 5432 | 数据库 |
| Redis | 6379 | 缓存 + Celery Result Backend |
| RabbitMQ AMQP | 5672 | 消息队列 |
| RabbitMQ Management | 15672 | 管理界面 |
| MinIO API | 9000 | 对象存储 API |
| MinIO Console | 9001 | 管理界面 |

### 12.2 健康检查

```bash
# 后端健康检查
curl http://localhost:8000/api/health
# 期望: {"status": "healthy", ...}

# 前端访问
curl http://localhost:3000
# 期望: HTML 内容

# PostgreSQL
pg_isready -h localhost -p 5432
# 期望: accepting connections

# Redis
redis-cli ping
# 期望: PONG

# RabbitMQ
sudo rabbitmqctl status | head -5
# 期望: 正常状态信息

# MinIO
curl http://localhost:9000/minio/health/live
# 期望: HTTP 200

# Celery Worker 状态
cd /opt/ai-test-platform/backend && source venv/bin/activate && set -a && source /opt/ai-test-platform/.env && set +a
celery -A app.celery_app inspect ping
# 期望: {"ok": "pong"}
```

### 12.3 访问系统

- **前端界面**: `http://<服务器IP>:3000`（开发模式）或 `http://<服务器IP>`（Nginx 生产模式）
- **API 文档 (Swagger)**: `http://<服务器IP>:8000/docs`
- **API 文档 (ReDoc)**: `http://<服务器IP>:8000/redoc`
- **RabbitMQ 管理界面**: `http://<服务器IP>:15672`（用户: aitp / aitp_secret_2026）
- **MinIO 管理界面**: `http://<服务器IP>:9001`（用户: aitp / aitp_secret_2026）

### 12.4 默认登录

- **用户名**: `admin`
- **密码**: `admin123`

---

## 13. 生产环境建议

### 13.1 使用 systemd 管理服务

为后端服务创建 systemd unit 文件，实现开机自启和崩溃自动重启:

```bash
# === FastAPI 后端 ===
sudo tee /etc/systemd/system/aitp-backend.service << 'EOF'
[Unit]
Description=AI Test Platform - Backend (FastAPI)
After=network.target postgresql.service redis-server.service rabbitmq-server.service minio.service

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/opt/ai-test-platform/backend
EnvironmentFile=/opt/ai-test-platform/.env
ExecStart=/opt/ai-test-platform/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# === Celery Worker ===
sudo tee /etc/systemd/system/aitp-celery-worker.service << 'EOF'
[Unit]
Description=AI Test Platform - Celery Worker
After=network.target rabbitmq-server.service redis-server.service

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/opt/ai-test-platform/backend
EnvironmentFile=/opt/ai-test-platform/.env
ExecStart=/opt/ai-test-platform/backend/venv/bin/celery -A app.celery_app worker --loglevel=info --concurrency=4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# === Celery Beat ===
sudo tee /etc/systemd/system/aitp-celery-beat.service << 'EOF'
[Unit]
Description=AI Test Platform - Celery Beat
After=network.target rabbitmq-server.service redis-server.service

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/opt/ai-test-platform/backend
EnvironmentFile=/opt/ai-test-platform/.env
ExecStart=/opt/ai-test-platform/backend/venv/bin/celery -A app.celery_app beat --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 替换用户名
sudo sed -i "s/YOUR_USERNAME/$USER/g" /etc/systemd/system/aitp-*.service

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable aitp-backend aitp-celery-worker aitp-celery-beat
sudo systemctl start aitp-backend aitp-celery-worker aitp-celery-beat
```

管理命令:

```bash
# 查看状态
sudo systemctl status aitp-backend
sudo systemctl status aitp-celery-worker
sudo systemctl status aitp-celery-beat

# 重启
sudo systemctl restart aitp-backend aitp-celery-worker aitp-celery-beat

# 查看日志
sudo journalctl -u aitp-backend -f
sudo journalctl -u aitp-celery-worker -f
```

### 13.2 安全加固清单

- [ ] 修改 `.env` 中的 `SECRET_KEY` 为随机长字符串
- [ ] 修改默认管理员密码 `admin123` 为强密码
- [ ] 修改 PostgreSQL `aitp` 用户密码
- [ ] 设置 Redis 密码
- [ ] 修改 RabbitMQ `aitp` 用户密码
- [ ] 修改 MinIO root 密码
- [ ] 设置 `DEBUG=false`
- [ ] 配置防火墙 (ufw) 仅开放必要端口
- [ ] 配置 HTTPS (Let's Encrypt + Nginx)
- [ ] 删除 RabbitMQ 默认 `guest` 用户

```bash
# 防火墙配置示例
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP (Nginx)
sudo ufw allow 443/tcp     # HTTPS
sudo ufw enable
```

### 13.3 日志管理

应用日志位于 `/app/data/logs/`:

```bash
# 实时查看应用日志
tail -f /app/data/logs/app.log

# 查看错误日志
tail -f /app/data/logs/error.log

# 日志文件会自动轮转（每天午夜，保留30天，错误日志保留90天）
```

---

## 14. 故障排查

### 14.1 后端启动失败

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| `connection refused` at port 5432 | PostgreSQL 未启动 | `sudo systemctl start postgresql` |
| `authentication failed` for user aitp | 密码不匹配 | 检查 `.env` 和数据库用户密码一致 |
| `relation does not exist` | 未执行数据库迁移 | `alembic upgrade head` |
| `No module named 'weasyprint'` | WeasyPrint 未安装或系统依赖缺失 | 安装系统依赖 + `pip install weasyprint` |
| `NameError: name 'os' is not defined` | logger.py 缺少 import os | 见步骤 9.1 |
| `AMQP connection failed` | RabbitMQ 未启动或凭据错误 | 检查 RabbitMQ 状态和 `.env` 配置 |
| `MinIO connection refused` | MinIO 未启动 | `sudo systemctl start minio` |

### 14.2 Celery Worker 启动失败

```bash
# 检查 RabbitMQ 连接
cd /opt/ai-test-platform/backend && source venv/bin/activate
set -a; source /opt/ai-test-platform/.env; set +a

# 测试连接
python -c "
import pika
connection = pika.BlockingConnection(pika.URLParameters('$CELERY_BROKER_URL' if 'CELERY_BROKER_URL' in dir() else f'amqp://$RABBITMQ_USER:$RABBITMQ_PASSWORD@$RABBITMQ_HOST:$RABBITMQ_PORT/'))
print('RabbitMQ connection OK')
connection.close()
"
```

### 14.3 前端构建失败

```bash
# 清除缓存重新安装
cd /opt/ai-test-platform/frontend
rm -rf node_modules package-lock.json
npm install
npm run build
```

### 14.4 数据库迁移回滚

```bash
cd /opt/ai-test-platform/backend
source venv/bin/activate

# 回退一个版本
alembic downgrade -1

# 回退到初始状态
alembic downgrade base

# 查看当前版本
alembic current

# 查看迁移历史
alembic history
```

### 14.5 查看服务运行状态一览

```bash
echo "=== 系统服务 ==="
sudo systemctl is-active postgresql redis-server rabbitmq-server minio
echo ""
echo "=== 应用服务 ==="
sudo systemctl is-active aitp-backend aitp-celery-worker aitp-celery-beat 2>/dev/null || echo "(systemd services not configured, running in foreground)"
echo ""
echo "=== 端口监听 ==="
ss -tlnp | grep -E '8000|3000|5432|6379|5672|15672|9000|9001'
```

---

## 15. 使用 Docker 部署（推荐生产方式）

> **何时用本章**：如果你希望像企业真实落地一样，用容器把整套系统（PostgreSQL / Redis / RabbitMQ / MinIO / 后端 / Celery / 前端）一键拉起，请使用本章，**可以忽略第 2–7 章在宿主机上手动安装各种中间件的步骤**。本项目自带 `docker-compose.yml` 与 `backend/Dockerfile`、`frontend/Dockerfile`，本就是按容器化设计的。
>
> **与裸机部署（第 1–14 章）的最大区别**：服务之间用 **Docker 网络内的服务名**（`postgres` / `redis` / `rabbitmq` / `minio` / `backend`）互相访问，而不是 `localhost`。所以 `.env` 里的主机名要填服务名（也就是 `.env.example` 的默认值），同时数据持久化到宿主机 `./data` 目录与 Docker 卷，而不是 `/app/data`。

### 15.1 在宿主机安装 Docker 与 Docker Compose

```bash
# 一键安装 Docker Engine + containerd（官方脚本）
curl -fsSL https://get.docker.com | sudo sh

# 安装 compose 插件（Docker 24+ 通常自带；若 docker compose 命令不存在则单独装）
sudo apt-get update
sudo apt-get install -y docker-compose-plugin

# 当前用户加入 docker 组（免 sudo 运行；需重新登录或执行 newgrp docker 生效）
sudo usermod -aG docker $USER

# 验证
docker --version
docker compose version
```

> 若在中国大陆网络拉取 Docker Hub 镜像慢，可配置镜像加速器（修改 `/etc/docker/daemon.json` 的 `registry-mirrors`），本手册不展开。

### 15.2 准备 .env（关键：主机名用服务名，不是 localhost）

```bash
cd /opt/ai-test-platform
cp .env.example .env
vim .env
```

Docker 模式下，请将下列主机名改回 **服务名**（与 `.env.example` 默认一致）：

```env
POSTGRES_HOST=postgres        # 不是 localhost
REDIS_HOST=redis              # 不是 localhost
RABBITMQ_HOST=rabbitmq        # 不是 localhost
MINIO_ENDPOINT=minio:9000     # 不是 localhost:9000

# 容器内路径，保持默认即可（compose 会把宿主机 ./data 挂载到 /app/data）
WORKSPACE_DIR=/app/data/repos
REPORT_DIR=/app/data/reports
LOG_DIR=/app/data/logs

# 其余（密码、SECRET_KEY、默认管理员等）与裸机一致，按需修改
```

> **原理**：后端、Celery Worker、Celery Beat 都在各自的容器里，通过 `env_file: .env` 读取配置。容器内 `localhost` 指向自己，必须用服务名才能访问到对应中间件容器。宿主机若要连这些中间件，因为 compose 已把端口发布出来，用 `localhost:端口` 即可（例如 `psql -h localhost -p 5432`）。

### 15.3 修复 logger.py（仍需，见第 9.1 节）

后端代码在容器内运行，`backend/app/utils/logger.py` 第 25 行 `os.getenv(...)` 仍缺 `import os`，不修的话后端容器会启动即崩溃（NameError）。请先按 [9.1](#91-修复-loggerpy-缺少-import-os) 加上 `import os`。

### 15.4 构建并启动全部服务

```bash
cd /opt/ai-test-platform

# 第一次或改了代码/Dockerfile 后，加 --build 重新构建镜像
docker compose up -d --build

# 查看各容器状态（STATUS 应为 healthy / running）
docker compose ps
```

启动顺序由 compose 的 `depends_on: condition: service_healthy` 保证：后端/Celery 会等 PostgreSQL、Redis、RabbitMQ、MinIO 都健康后再启动。

> **端口冲突提示**：如果你之前按裸机手册在宿主机装过 PostgreSQL/Redis/RabbitMQ/MinIO，它们会占用 5432/6379/5672/9000/15672/9001，导致 compose 端口映射绑定失败。请先停止并禁用这些宿主机服务：
> ```bash
> sudo systemctl stop postgresql redis-server rabbitmq-server minio
> sudo systemctl disable postgresql redis-server rabbitmq-server minio
> ```
> 或改 `docker-compose.yml` 里的端口映射（如 `"5433:5432"`）。

### 15.5 初始化数据库（扩展 + 迁移）

```bash
# 1) 启用 uuid-ossp 扩展（alembic 迁移依赖 UUID 类型）
docker compose exec postgres psql -U aitp -d ai_test_platform -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'

# 2) 执行 Alembic 迁移
docker compose exec backend alembic upgrade head
```

> RabbitMQ 用户无需手动创建：compose 已通过 `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` 在容器首次启动时自动建好 `aitp` 用户（见 `docker-compose.yml`）。MinIO 的 bucket 由后端 lifespan 启动时自动创建。

### 15.6 验证

```bash
# 后端健康检查
curl http://localhost:8000/api/health

# 前端（nginx 容器，发布到 3000）
curl http://localhost:3000

# 查看某服务日志
docker compose logs -f backend
docker compose logs -f celery-worker
```

访问地址与裸机一致：前端 `http://<IP>:3000`，API 文档 `http://<IP>:8000/docs`，RabbitMQ 管理 `http://<IP>:15672`，MinIO 控制台 `http://<IP>:9001`。默认管理员 `admin/admin123`。

### 15.7 常用运维命令

```bash
docker compose ps                                  # 状态
docker compose logs -f <service>                  # 实时日志（backend/celery-worker/celery-beat/postgres/redis/rabbitmq/minio/frontend）
docker compose restart backend                    # 重启单个服务
docker compose down                               # 停止并删除容器（数据卷保留）
docker compose down -v                            # 停止并删除容器+数据卷（慎用，会清空数据）
docker compose up -d --build                     # 代码更新后重新构建
```

### 15.8 设置开机自启（生产建议）

当前 `docker-compose.yml` 未配置重启策略。生产环境请给每个 service 加 `restart: unless-stopped`（或 `always`）。例如在 `backend` / `celery-worker` / `celery-beat` / `postgres` / `redis` / `rabbitmq` / `minio` / `frontend` 配置块下各加一行：

```yaml
    restart: unless-stopped
```

Docker Engine 本身开机自启后，带此策略的容器会在宿主机重启后自动拉起，等价于裸机部署的 systemd 自启。

### 15.9 Docker 与裸机部署差异对照表

| 项目 | 裸机部署（第 1–14 章） | Docker 部署（本章） |
|------|----------------------|---------------------|
| 中间件安装 | 宿主机 `apt install` PG/Redis/RabbitMQ/MinIO | 容器自动拉起，无需手动装 |
| Python/Node 环境 | 宿主机建 venv / npm install | 镜像内自带，宿主机无需装 |
| `.env` 服务主机 | `localhost` | 服务名 `postgres`/`redis`/`rabbitmq`/`minio` |
| 数据目录 | 宿主机 `/app/data/...` | 宿主机 `./data`（挂载到容器 `/app/data`）+ Docker 卷 |
| 启动方式 | 手动 uvicorn + celery + npm | `docker compose up -d --build` |
| 数据库迁移 | 宿主机 venv 里 `alembic upgrade head` | `docker compose exec backend alembic upgrade head` |
| RabbitMQ 用户 | 手动 `rabbitmqctl add_user` | compose 的 `RABBITMQ_DEFAULT_*` 自动创建 |
| 开机自启 | systemd unit 文件 | compose `restart: unless-stopped` |
| WeasyPrint 依赖 | 宿主机装 libcairo2/libpango | 已在 `backend/Dockerfile` 内置 |
| 端口冲突风险 | 无（本机直连） | 若宿主机已装中间件会冲突，需先停掉 |

### 15.10 已知坑

- **pysvn 构建可能失败**：`backend/Dockerfile` 装了 `subversion` 但没装 `libsvn-dev`，而 `requirements.txt` 里的 `pysvn==1.9.15` 需要 `libsvn-dev` 才能编译。若镜像构建卡在 `pip install pysvn`，二选一：① 在 `backend/Dockerfile` 的系统依赖里加 `libsvn-dev`；② 若不用 SVN，直接从 `requirements.txt` 注释掉 `pysvn==1.9.15`。
- **logger.py 的 import os 必须修**（见 15.3），否则后端容器无限重启。
- **端口冲突**（见 15.4 提示）：宿主机已有中间件时先停用。
- **首次构建较慢**：Python 依赖与前端 `npm install` + `npm run build` 会拉较多包，耐心等待；可在构建时加 `--no-cache` 排查缓存问题。
- **Docker 构建报 `commit failed: rename .../ingest/.../data .../blobs/sha256/...: no such file or directory`**：这是 BuildKit 把镜像层提交到 containerd 内容仓库时失败（不是网络问题，其它镜像能拉成功就证明网络正常）。常见三种诱因与对应处理：
  1. **磁盘/Inode 满**：`df -h /var/lib/docker` 与 `df -i /var/lib/docker` 检查；满了就清理或把 `data-root` 迁到大盘（迁移语法见下方注意）。
  2. **并发构建在共享内容仓库里 race**：`docker compose up --build` 会并行构建 backend/frontend/celery-worker/celery-beat，多个构建共享同一 content store 易触发该 rename 竞态。改为**逐个串行构建**最稳：`docker compose build backend && docker compose build frontend && docker compose build celery-worker && docker compose build celery-beat`，再 `docker compose up -d`。
  3. **containerd 内容仓库本身兼容/损坏**：在 `/etc/docker/daemon.json` 关闭 containerd snapshotter，让 Docker 用经典镜像仓库，彻底绕开这条 commit 路径：
     ```json
     { "features": { "containerd-snapshotter": false } }
     ```
     改完 `sudo systemctl restart docker`，再 `docker compose up -d --build`。
  > **通用兜底**：无论哪种诱因，先 `docker builder prune -a -f && docker buildx prune -a -f` 清掉损坏/残留的 ingest 状态，再重试构建，通常能直接消除该报错。
  > **注意 `mv` 迁移 data-root 的语法坑**：把 `/var/lib/docker` 迁到大数据盘时，日期后缀要用 `$(date +%Y%m%d)`（单 `$` + 圆括号），**不要**写成 `$((date +%Y%m%d)`（双 `$` 是未闭合的算术展开，bash 会直接报语法错、整条 `mv` 不执行，导致 Docker 仍在原（可能已满的）盘上启动）。正确写法：
  > ```bash
  > sudo systemctl stop docker
  > sudo mv /var/lib/docker      /var/lib/docker.bak.$(date +%Y%m%d)
  > sudo mv /var/lib/containerd  /var/lib/containerd.bak.$(date +%Y%m%d)
  > sudo systemctl start docker
  > ```
- **Docker 拉取镜像报 `short read: expected N bytes but got 0: unexpected EOF`**（如 `node:22-alpine` 元数据拉取失败）：这是 Docker Hub 网络连接中途被截断的**瞬时网络抖动**，属远程拉取读不全，与上面的 `commit failed: rename`（本地 containerd 提交失败）是两类不同错误。处理：① 直接重试，`docker compose build frontend` 多数第二次就过（backend/celery 已缓存不会重来）；② 更稳：先 `docker pull node:22-alpine` 单独预热拉取再构建；③ 若 VM 到 Docker Hub 持续不稳，配国内镜像加速：在 `/etc/docker/daemon.json` 加 `"registry-mirrors": ["https://docker.m.daocloud.io"]`（或阿里云加速器地址），`systemctl restart docker` 后重试。
- **架构选型：保持「多容器、一服务一容器」（当前方案），不要改成单容器**：本项目 `docker-compose.yml` 为 postgres/redis/rabbitmq/minio/backend/celery-worker/celery-beat/frontend 共 8 个独立容器。多容器可独立扩缩（如 `--scale celery-worker=4` 只扩异步执行）、独立重启/更新、故障与资源隔离、按容器做健康检查、并直接对应 K8s 部署；单容器（supervisord 全塞一起）是反模式——无法扩缩、无隔离、镜像巨大、上 K8s 需重写。仅「笔记本随手跑 demo」场景单容器看似省事，但 compose 本身也是一条命令，多容器并未牺牲便利性。
- **数据备份**：业务数据在宿主机 `./data` 目录与 Docker 命名卷（`postgres_data`/`redis_data`/`rabbitmq_data`/`minio_data`）。备份可停服后拷贝 `./data` 与 `/var/lib/docker/volumes/` 下对应卷；或 `docker compose exec <svc> ...` 导出。

### 15.11 Docker 部署快速清单

```
□ 1. 宿主机安装 Docker + docker-compose-plugin（15.1）
□ 2. 项目代码放置 /opt/ai-test-platform
□ 3. cp .env.example .env，主机名改回服务名 postgres/redis/rabbitmq/minio（15.2）
□ 4. 修复 logger.py 的 import os（15.3 / 9.1）
□ 5. （可选）停掉宿主机已装的 PG/Redis/RabbitMQ/MinIO，避免端口冲突（15.4）
□ 6. docker compose up -d --build
□ 7. docker compose ps 确认全部 healthy
□ 8. docker compose exec postgres ... CREATE EXTENSION uuid-ossp（15.5）
□ 9. docker compose exec backend alembic upgrade head（15.5）
□ 10. curl http://localhost:8000/api/health 验证
□ 11. 浏览器打开 http://<IP>:3000，用 admin/admin123 登录
□ 12. （生产）给各服务加 restart: unless-stopped（15.8）
```

## 附录: 快速启动检查清单

```
□ 1. 系统更新 + 基础工具安装
□ 2. PostgreSQL 16 安装 + 创建数据库/用户
□ 3. Redis 7 安装 + 启动
□ 4. RabbitMQ 3.13 安装 + 创建用户
□ 5. MinIO 安装 + systemd 服务
□ 6. Python 虚拟环境 + 后端依赖安装
□ 7. Node.js + 前端依赖安装
□ 8. .env 文件创建（主机改为 localhost）
□ 9. alembic.ini 数据库 URL 确认
□ 10. logger.py 添加 import os
□ 11. alembic upgrade head（数据库迁移）
□ 12. 启动 FastAPI 后端 (端口 8000)
□ 13. 启动 Celery Worker
□ 14. 启动 Celery Beat
□ 15. 启动前端 (npm run dev 或 npm run build + Nginx)
□ 16. 访问 http://localhost:3000 验证
□ 17. 使用 admin/admin123 登录验证
□ 18. curl http://localhost:8000/api/health 健康检查
```

---

*手册版本: 1.3 | 最后更新: 2026-08-06（新增第 15 章 Docker 部署方式，含与裸机部署差异对照表、快速清单、已知坑）*
