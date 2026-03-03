FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONPATH=/app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .

# --- Development stage ---
FROM base AS dev
RUN uv pip install --system -e ".[dev]" 2>/dev/null || true
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- Production stage ---
FROM base AS production
RUN uv pip install --system -e "." 2>/dev/null || true
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
