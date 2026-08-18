FROM python:3.12-slim

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libxml2-dev \
    libxslt-dev \
    libffi-dev \
    libcairo2-dev \
    libpango1.0-dev \
    git \
    subversion \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖`
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录（日志、仓库、报告、上传）
RUN mkdir -p /app/data/logs /app/data/repos /app/data/reports /app/data/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
