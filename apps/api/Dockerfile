# API, worker and scheduler image (same image, different command)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# ffmpeg (video/audio, subtitles via libass), fonts for Arabic text, Pango for PDF reports
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core fonts-noto-core libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra pdf --no-install-project
COPY . .
RUN uv sync --frozen --no-dev --extra pdf

ENV PATH="/app/.venv/bin:$PATH" SAI_STORAGE_DIR=/data/storage
EXPOSE 8000
HEALTHCHECK CMD curl -fs http://localhost:8000/api/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${SAI_WEB_WORKERS:-2} --proxy-headers --forwarded-allow-ips='*'"]
