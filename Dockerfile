# ============================================================
# 检定排程系统 — 算法服务镜像（Python 3.10）
# ------------------------------------------------------------
# 构建：docker build -t jiankeng-scheduler .
# 运行：docker run -d -p 5000:5000 jiankeng-scheduler
#   -e SERVER_HOST=10.x.x.x -e SERVER_PORT=8080 可覆盖监听地址
# 说明：算法串行同步运行、单线程启动，镜像内保持单进程单线程。
# ============================================================

FROM python:3.10-slim

# 基础环境：日志立即输出（否则 docker logs 无输出）
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先复制依赖清单并安装，利用 Docker 层缓存（依赖不变时不重装）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码（docs/tests/缓存等已被 .dockerignore 排除）
COPY . .

# 默认环境变量（运行时可用 -e 覆盖）
ENV SERVER_HOST=0.0.0.0 \
    SERVER_PORT=5000 \
    LOG_LEVEL=INFO

# 非 root 运行（更安全）；/app 保持可写，便于 CLI 兑底在容器内输出 Excel
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# 服务监听端口
EXPOSE 5000

# 健康检查：TCP 探测监听端口（不触发算法，避免每次探测跑一次排程）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ.get('SERVER_PORT', '5000'))), 5).close()"

# 启动算法服务（入口等价 `python main.py`）
CMD ["python", "main.py"]
