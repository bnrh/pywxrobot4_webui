FROM node:20-bookworm-slim AS frontend

WORKDIR /build
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY vite.config.js ./
COPY static ./static
COPY frontend ./frontend
COPY scripts ./scripts
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /build/static/dist ./static/dist
COPY --from=frontend /build/frontend/index.html ./frontend/index.html

EXPOSE 28080

CMD ["python", "main.py"]
