# Stage 1: Build frontend static export
FROM node:20-slim AS frontend-build

WORKDIR /build
COPY frontend/ .
RUN npm ci && npm run build

# Stage 2: Production image with backend + static frontend
FROM python:3.12-slim

WORKDIR /app

ENV DB_PATH=/app/db/finally.db \
    PYTHONUNBUFFERED=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install Python dependencies
COPY backend/ backend/
RUN cd backend && uv sync --frozen --no-dev

# Copy frontend build output as static files
COPY --from=frontend-build /build/out/ static/

RUN mkdir -p /app/db

EXPOSE 8000

WORKDIR /app/backend

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).read()" || exit 1

CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
