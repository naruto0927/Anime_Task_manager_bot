# ── Build stage ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for cryptography / motor / python-psutil
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --no-create-home --shell /bin/false botuser

# Create required directories
RUN mkdir -p logs backups/daily backups/manual exports/csv exports/json exports/sheets \
 && chown -R botuser:botuser /app

COPY --chown=botuser:botuser . .

USER botuser

# Health check — just verify the process is alive
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os; os.path.exists('logs/bot.log') or exit(1)"

CMD ["python", "-u", "bot.py"]
