# Stage 1: install dependencies into an isolated venv
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /bin/

WORKDIR /app
COPY requirements-api.txt ./
RUN uv venv .venv && uv pip install --no-cache -r requirements-api.txt

# Stage 2: lean runtime image
FROM python:3.12-slim AS runner
WORKDIR /app

RUN addgroup --system --gid 1001 appgroup \
    && adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser

COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --chown=appuser:appgroup api ./api
COPY --chown=appuser:appgroup agents ./agents
COPY --chown=appuser:appgroup adapters ./adapters
COPY --chown=appuser:appgroup src ./src

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health')" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8010"]
