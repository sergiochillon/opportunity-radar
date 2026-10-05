# Multi-stage lightweight Dockerfile for Opportunity Radar
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --user .

# Final stage
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/radaruser/.local/bin:$PATH"

ARG USER_UID=1000
ARG USER_GID=1000

# Create non-root user and group (supports build-time UID/GID customization)
RUN (getent group ${USER_GID} || groupadd -g ${USER_GID} radaruser) && \
    (getent passwd ${USER_UID} || useradd -u ${USER_UID} -g ${USER_GID} -m -s /bin/bash radaruser)

# Copy installed packages from builder
COPY --from=builder /root/.local /home/radaruser/.local
RUN chown -R radaruser:radaruser /home/radaruser/.local

# Copy application source code
COPY --chown=radaruser:radaruser config /app/config
COPY --chown=radaruser:radaruser storage /app/storage
COPY --chown=radaruser:radaruser pipeline /app/pipeline
COPY --chown=radaruser:radaruser intelligence /app/intelligence
COPY --chown=radaruser:radaruser collectors /app/collectors
COPY --chown=radaruser:radaruser notifications /app/notifications
COPY --chown=radaruser:radaruser scripts /app/scripts
COPY --chown=radaruser:radaruser pyproject.toml /app/pyproject.toml

# Create data and logs directories with correct non-root permissions
RUN mkdir -p /app/data /app/logs && \
    chown -R radaruser:radaruser /app/data /app/logs

USER radaruser

VOLUME ["/app/data", "/app/logs"]

# Healthcheck verifies Python runtime and DB query capability
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python3 -c "import os, sqlite3; path = os.environ.get('DATABASE_PATH', 'data/radar.db'); conn = sqlite3.connect(path); conn.execute('PRAGMA integrity_check;'); conn.close()" || exit 1

ENTRYPOINT ["python3", "-u", "scripts/run_radar.py", "--daemon"]
