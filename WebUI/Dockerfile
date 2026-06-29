# Build frontend
FROM node:22-slim AS node-builder

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Python build stage
FROM python:3.12-slim AS python-builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app/ ./app/
COPY static/ ./static/
COPY run.py ./
COPY alembic.ini ./
COPY alembic/ ./alembic/
RUN pip install --no-cache-dir -e "."

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy Python packages and app
COPY --from=python-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-builder /usr/local/bin/alembic /usr/local/bin/uvicorn /usr/local/bin/
COPY --from=python-builder /app /app

# Copy built frontend
COPY --from=node-builder /app/static/dist /app/static/dist

# Ensure DB directory is writable
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data /app/static/dist
ENV DATABASE_URL="sqlite+aiosqlite:///./data/zigbeehub.db"

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080"]
