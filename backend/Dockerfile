FROM python:3.12-slim

# 系统依赖
# fonts-wqy-zenhei：中文字体（文泉驿正黑）。
#   没有它时 weasyprint 渲染 PDF 找不到 CJK 字形 → 中文全部变成方块/乱码；
#   matplotlib 画静态图表同样需要它（见 app/modules/report/static_charts.py）。
#   选它而非 fonts-noto-cjk 是因为体积小（约 15MB vs 200MB+），构建拉取更快。
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libxml2-dev \
    libxslt-dev \
    libffi-dev \
    libcairo2-dev \
    libpango1.0-dev \
    fonts-wqy-zenhei \
    git \
    subversion \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/app
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
