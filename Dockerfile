FROM python:3.12-slim

# psycopg[binary] ships its own libpq, so no build toolchain is needed here.
# Keeping the image slim matters: Cloud Run cold starts read the whole layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements first so a code change does not reinstall the dependency tree.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts
COPY evals ./evals

# Cloud Run injects PORT and terminates TLS in front of us. One worker per
# instance: concurrency is handled by Cloud Run spawning instances, and the
# LLM pacer's rate limit is per-process — extra workers would multiply it.
ENV PORT=8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
