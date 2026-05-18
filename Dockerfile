# Plan 35 — filesystem-mcp (VDR) Docker image
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    PORT=8016 \
    VDR_ROOT_PATH=/data/vdr

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system .

COPY src ./src

# Persistent VDR data
RUN mkdir -p /data/vdr
VOLUME /data/vdr

EXPOSE 8016
CMD ["gestnova-filesystem-http"]
