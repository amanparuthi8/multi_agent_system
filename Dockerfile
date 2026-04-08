# ============================================================
# Dockerfile — Multi-Agent AI System
# Base: python:3.12-slim  (Lab 2 Python 3.12 requirement)
# Pattern: Lab 1 Cloud Run — stateless, env-configured
# ============================================================

# Stage 1: dependency builder
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv==0.4.29
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Stage 2: lean runtime image
FROM python:3.12-slim AS runtime

RUN groupadd --gid 1001 appuser && \
    useradd  --uid 1001 --gid appuser --no-create-home appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY agents/      ./agents/
COPY api/         ./api/
COPY database/    ./database/
COPY tools/       ./tools/
COPY workflows/   ./workflows/
COPY mcp_toolbox/ ./mcp_toolbox/

ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8080

CMD ["sh", "-c", \
     "uvicorn api.main:app --host 0.0.0.0 --port $PORT --workers 2 --proxy-headers --forwarded-allow-ips='*' --log-level info"]
