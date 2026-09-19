# llm-serve inference server (CPU). Build:  docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t llm-serve .
#
# The image bakes in the GPT-2 weights so a pod never downloads anything at start-up, and the
# runtime sets HF_HUB_OFFLINE=1 to guarantee it. Model version = image tag.
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# Dependencies first so this layer is cached until requirements change.
COPY requirements-serve.txt .
RUN pip install -r requirements-serve.txt

# Weights: fetched once at build time.
RUN python -c "from transformers import GPT2LMHeadModel, GPT2TokenizerFast; \
GPT2LMHeadModel.from_pretrained('gpt2'); GPT2TokenizerFast.from_pretrained('gpt2')"

COPY engine ./engine

# Never run as root.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin llm \
 && chmod -R a+rX /opt/hf /app
USER 10001

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} \
    HF_HUB_OFFLINE=1 \
    LLM_SERVE_THREADS=4 \
    LLM_SERVE_CONFIG='{"backend":"paged","batching":"continuous","max_batch":16,"kv_budget_mib":1024,"block_size":16,"preemption":true,"max_queue":64}'

EXPOSE 8000

# Readiness, not just liveness: the model is loaded and warmed before this passes.
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2).status==200 else 1)"

# ONE worker: the process owns the model and the KV pool. Scale out with replicas.
ENTRYPOINT ["python", "-m", "uvicorn", "engine.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
