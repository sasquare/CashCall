# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools needed for some Python packages (bcrypt, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime image ─────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user for security
RUN groupadd -r cashcall && useradd -r -g cashcall -d /app -s /sbin/nologin cashcall

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=cashcall:cashcall . .

# Persistent data directory for SQLite; override DATABASE_URL for Postgres in prod
RUN mkdir -p /data && chown cashcall:cashcall /data && \
    chmod +x /app/scripts/entrypoint.sh

# Drop to non-root
USER cashcall

EXPOSE 8000

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
