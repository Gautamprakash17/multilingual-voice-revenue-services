FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
COPY backend/alembic /app/backend/alembic
COPY backend/alembic.ini /app/backend/alembic.ini
COPY config /app/config

WORKDIR /app/backend
RUN pip install --no-cache-dir -e ".[dev]"

ENV PYTHONUNBUFFERED=1 \
    BOUNDARY_POLICY_PATH=/app/config/boundary/policies.yaml \
    DOCUMENT_STORAGE_PATH=/app/data/documents

RUN mkdir -p /app/data/documents

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
