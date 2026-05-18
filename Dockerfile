# syntax=docker/dockerfile:1

# ── Frontend build stage ────────────────────────────────────────────────────
FROM --platform=$BUILDPLATFORM oven/bun:1 AS frontend-builder

WORKDIR /app
COPY lightrag_webui/ ./lightrag_webui/

RUN --mount=type=cache,target=/root/.bun/install/cache \
    cd lightrag_webui \
    && bun install --frozen-lockfile \
    && bun run build

# ── Python build stage ──────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_CACHE_DIR=/root/.cache/uv
ENV UV_HTTP_TIMEOUT=120
ENV UV_RETRIES=5
ENV UV_CONCURRENT_DOWNLOADS=4

WORKDIR /app

# Create a dedicated venv so packages don't go to system Python
RUN uv venv /app/.venv

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:/root/.local/bin:${PATH}"

# ── Copy project sources ─────────────────────────────────────────────────────
COPY pyproject.toml setup.py ./
COPY lightrag/ ./lightrag/
COPY legal_rag/ ./legal_rag/
COPY --from=frontend-builder /app/lightrag/api/webui ./lightrag/api/webui

# ── Install lightrag package code only (skip heavy unused base deps) ─────────
# Skips: google-api-core, google-genai (Gemini only), pandas, xlsxwriter,
#        pypinyin, python-pptx, openpyxl — none used with vLLM deployment.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-deps .

# ── Install runtime dependencies ─────────────────────────────────────────────
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install \
        `# FastAPI server` \
        fastapi uvicorn gunicorn \
        aiofiles python-multipart psutil pytz distro ascii_colors \
        `# Auth` \
        "bcrypt>=4.0.0" "PyJWT>=2.8.0,<3.0.0" "python-jose[cryptography]" \
        `# HTTP` \
        "httpx>=0.28.1" aiohttp \
        `# LightRAG core` \
        networkx "numpy>=1.24.0,<3.0.0" \
        nano-vectordb json_repair pipmaster tenacity tiktoken \
        "aiosqlite>=0.20.0" python-dotenv pydantic setuptools packaging \
        `# LLM — OpenAI-compatible (vLLM) + Ollama` \
        "openai>=2.0.0,<3.0.0" \
        "ollama>=0.1.0,<1.0.0" \
        `# Document processing (PDF + Word)` \
        "pypdf>=6.1.0" "python-docx>=0.8.11,<2.0.0" "pycryptodome>=3.0.0,<4.0.0" \
        `# LegalRAG pipeline` \
        "pdfplumber>=0.11.0" \
        "qdrant-client>=1.16.0,<2.0.0" \
        "neo4j>=5.0.0,<7.0.0" \
        `# Semantic chunking` \
        "langchain-experimental>=0.3.0,<0.4.0" \
        "langchain-openai>=0.3.0,<0.4.0"

# ── Pre-populate tiktoken tokeniser data ────────────────────────────────────
RUN --mount=type=cache,target=/root/.cache/uv \
    mkdir -p /app/data/tiktoken \
    && lightrag-download-cache --cache-dir /app/data/tiktoken || true

# ── Final runtime stage — copy only ─────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/lightrag ./lightrag
COPY --from=builder /app/legal_rag ./legal_rag
COPY pyproject.toml setup.py ./

ENV VIRTUAL_ENV=/app/.venv
ENV PATH=/app/.venv/bin:$PATH

RUN mkdir -p /app/data/rag_storage /app/data/inputs /app/data/tiktoken
COPY --from=builder /app/data/tiktoken /app/data/tiktoken

ENV TIKTOKEN_CACHE_DIR=/app/data/tiktoken
ENV WORKING_DIR=/app/data/rag_storage
ENV INPUT_DIR=/app/data/inputs

EXPOSE 9621
ENTRYPOINT ["python", "-m", "lightrag.api.lightrag_server"]
