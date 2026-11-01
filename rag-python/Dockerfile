FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY rag-python/pyproject.toml /app/rag-python/
RUN pip install --no-cache-dir -e /app/rag-python

COPY rag-python /app/rag-python
COPY data /app/data

WORKDIR /app/rag-python

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
