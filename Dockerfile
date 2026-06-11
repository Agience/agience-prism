# syntax=docker/dockerfile:1
# Agience Prism — embeddings host (bge-m3), CPU image. NO model baked.
#
# Build from the repo root (host SDK comes from a named build context — no PyPI):
#   docker build --build-context host=../agience-host -f Dockerfile -t <ns>/agience-prism .
# Once agience-host is on PyPI: drop --build-context and the two "host" lines below.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/hf

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch wheel (smaller than CUDA torch).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Host SDK (Apache-2.0) from the named build context.
COPY --from=host . /tmp/agience-host
RUN pip install --no-cache-dir /tmp/agience-host

# Prism (this repo) + model deps. agience-host is already satisfied above.
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

EXPOSE 8083
CMD ["uvicorn", "agience_prism.app:app", "--host", "0.0.0.0", "--port", "8083", "--timeout-graceful-shutdown", "10"]
