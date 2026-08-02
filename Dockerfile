# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

WORKDIR /app

# ── 系统依赖 ──
# 基础：编译/SQLite 运行时。
# Chromium 运行时库：Playwright 浏览器工具依赖（缺失会导致 Docker 部署后浏览器能力整体失效）。
# fonts-noto-cjk：中文等 CJK 字形，保证浏览器截图/PDF 渲染不乱码。
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libsqlite3-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    fonts-noto-cjk \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 安装 Playwright Chromium ──
# 系统库已在上方显式装好，这里只下载浏览器二进制；
# 浏览器二进制统一放到 /app/.playwright 并由下方 chown 交给 appuser 读取。
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright
RUN python -m playwright install chromium

# 应用代码
COPY . .

# 创建数据目录
RUN mkdir -p data/logs data/sessions data/rag

# 安全：非 root 用户运行
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# ── 运行时配置 ──
# 容器内必须绑 0.0.0.0，否则宿主机的端口映射无法连入。
# 注：访问守卫默认关闭，容器启动即「打开即用、零门禁、无需口令」；
# 真正的网络边界由 compose 的 ports 映射控制（默认只绑宿主机环回）。
# 真正的网络边界请由 compose 的端口映射控制（默认只绑宿主机环回）。
ENV HOST=0.0.0.0
ENV PORT=38473
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

EXPOSE 38473

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:38473/health || exit 1

CMD ["python", "run.py"]
