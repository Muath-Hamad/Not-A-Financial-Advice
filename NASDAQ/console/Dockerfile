# nafa-console — the Operations Console (docs/08 §3.3): FastAPI read API +
# indexer + the built web UI on one port. Build from NASDAQ/console:
#   docker build -t nafa-console .
# The ledger is a git clone under /data (Phases 1–3) that the indexer pulls
# every minute; the container never holds broker keys in M0.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api/nafa_console ./nafa_console
COPY --from=web /web/dist ./web/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

ENV CONSOLE_STATIC_DIR=/app/web/dist \
    CONSOLE_DB=/data/console.db \
    CONSOLE_PKG_DIR=/data/repo/NASDAQ \
    CONSOLE_GIT_PULL=1 \
    CONSOLE_INDEX_EVERY_S=60 \
    PYTHONUNBUFFERED=1

# Unraid convention: nobody:users, so /mnt/user/appdata stays writable.
USER 99:100
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"
ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
