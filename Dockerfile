# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/
COPY run.py ./
COPY alembic.ini ./
COPY alembic/ ./alembic/

RUN pip install --no-cache-dir -e "."

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy installed packages and app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/alembic /usr/local/bin/uvicorn /usr/local/bin/
COPY --from=builder /app /app

# Ensure DB directory is writable
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data
ENV DATABASE_URL="sqlite+aiosqlite:///./data/zigbeehub.db"

USER appuser

EXPOSE 8080

# Run migrations then start server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080"]
