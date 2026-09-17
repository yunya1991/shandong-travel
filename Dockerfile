# AI 旅行手册 · 单容器云端部署（Task 23+ 部署增强）
# 同一镜像同时提供：
#   - FastAPI 后端（API + WebSocket + SPA 静态文件）
#   - 前端静态文件（构建期从 app/ 复制到 /app/static）
# cockpit 驾驶舱在云端关闭（COCKPIT_DISABLE=1），前端通过 WebSocket 直连后端
FROM python:3.11-slim AS base

# 系统依赖：Scrapling 抓取需要的编译工具 + 浏览器运行库（精简版）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) 先装 Python 依赖（利用 Docker 层缓存）
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt

# 2) 复制后端代码
COPY server/ /app/server/

# 3) 复制前端静态文件 → /app/static（FastAPI 通过 TG_STATIC_DIR 挂载）
COPY app/ /app/static/

# 4) SQLite 数据路径（Render 免费套餐无持久化磁盘，重启丢失；
#    若需持久化请挂载 Render Disk 到 /data 并设 TG_DB_PATH=/data/cache.db）
RUN mkdir -p /data
ENV TG_DB_PATH=/data/cache.db \
    TG_STATIC_DIR=/app/static \
    COCKPIT_DISABLE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

# 健康检查：FastAPI /health 端点
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); print('ok')" || exit 1

# 启动 uvicorn（生产模式，无 --reload）
WORKDIR /app/server
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
