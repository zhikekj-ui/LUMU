# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

WORKDIR /app

# ── 系统依赖 ──
# 基础：编译/SQLite 运行时。
# Chromium 运行时库：Playwright 浏览器工具依赖（缺失会导致 Docker 部署后浏览器能力整体失效）。
# fonts-noto-cjk：中文等 CJK 字形，保证浏览器截图/PDF 渲染不乱码（面向国内用户）。
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
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 安装 Playwright Chromium ──
# 系统库已上方显式装好，这里只下载浏览器二进制；
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

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

CMD ["python", "run.py"]
