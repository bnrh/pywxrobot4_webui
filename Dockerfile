# syntax=docker/dockerfile:1

# ---------- Frontend (Vite) ----------
FROM node:20-bookworm-slim AS frontend

WORKDIR /build

COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY vite.config.js ./
COPY static ./static

# 只做 Vite 打包；资源戳在 Python 阶段写入（node 镜像通常无 Python）
RUN npx vite build


# ---------- Runtime ----------
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 按功能分包后的应用代码（根目录仅保留启动入口）
COPY main.py ./
COPY core ./core
COPY server ./server
COPY runtime ./runtime
COPY messaging ./messaging
COPY manager ./manager
COPY routes ./routes
COPY ai_assistant ./ai_assistant
COPY plugins ./plugins
COPY utils ./utils
COPY frontend ./frontend
COPY static ./static
COPY scripts ./scripts

# 覆盖为多阶段构建出的前端产物，并写入 index.html 资源戳
COPY --from=frontend /build/static/dist ./static/dist
RUN python scripts/stamp_frontend_assets.py \
    && mkdir -p uploads logs

EXPOSE 28080

# 容器内建议将系统设置 host 设为 0.0.0.0，否则仅监听 127.0.0.1 无法从宿主机访问
CMD ["python", "main.py"]
