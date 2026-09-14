FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
# curl: used by the platform's in-container HTTP healthcheck against /healthz (spec §11.2).
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
RUN pip install uv

# 1) Install dependencies only, as a cached layer. --no-install-project skips building the
#    local `problem-radar` package here (its source isn't copied yet), which would otherwise
#    fail the frozen sync.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Copy the app and install the project itself against the already-resolved deps.
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "pr.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
