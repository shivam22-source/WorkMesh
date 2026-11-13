# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf-cache

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --default-timeout=120 --retries 5 torch --index-url https://download.pytorch.org/whl/cpu

COPY rag-python/pyproject.toml /build/rag-python/
COPY rag-python/app /build/rag-python/app
RUN pip install --no-cache-dir --default-timeout=120 --retries 5 /build/rag-python

# Pre-download the default embedding model so runtime containers boot offline cleanly
RUN mkdir -p /opt/hf-cache && python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"


FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 workmesh \
    && useradd --system --uid 10001 --gid workmesh --create-home --home-dir /home/workmesh workmesh

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=workmesh:workmesh /opt/hf-cache /app/.cache/huggingface
COPY --chown=workmesh:workmesh rag-python /app/rag-python
COPY --chown=workmesh:workmesh data /app/data
COPY --chown=workmesh:workmesh demo-ui /app/demo-ui

WORKDIR /app/rag-python
USER workmesh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["curl", "-fsS", "http://localhost:8000/health"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
