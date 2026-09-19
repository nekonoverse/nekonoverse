FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONPATH=/app
# glibc malloc はスレッド/プロセスごとにアリーナを確保し (デフォルト最大 = コア数 x 8)、
# 長時間稼働で解放済みメモリを OS に返さずアリーナ断片化で RSS が肥大化しやすい。
# アリーナ数を制限して常駐メモリの伸びを抑える。
ENV MALLOC_ARENA_MAX=2

RUN pip install --no-cache-dir uv

COPY pyproject.toml .

# --- Development stage ---
FROM base AS dev
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN uv pip install --system -e ".[dev]" 2>/dev/null || true
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- Production stage ---
FROM base AS production
ARG GIT_HASH=""
ARG GIT_BRANCH=""
RUN uv pip install --system -e "." 2>/dev/null || true
COPY . .
RUN if [ -n "$GIT_HASH" ]; then echo "${GIT_BRANCH}:${GIT_HASH}" > /app/GIT_VERSION; fi
EXPOSE 8000
# uvicorn の worker はプロセスごとに独立した Python ランタイム(FastAPI/SQLAlchemy/
# cryptography/Pillow 等の全依存)を保持するためメモリの主要因になる。
# UVICORN_WORKERS で環境ごとにチューニングできるようにし、デフォルトは控えめな値にする。
CMD uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}
