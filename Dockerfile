FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /app/backend/pyproject.toml
RUN pip install --no-cache-dir -e /app/backend

COPY backend /app/backend
RUN pip install --no-cache-dir -e /app/backend

# non-root
RUN useradd -m omnimcp
RUN mkdir -p /var/lib/omnimcp/storage /var/lib/omnimcp/workspaces && chown -R omnimcp /var/lib/omnimcp /app
USER omnimcp

ENV OMNIMCP_HOST=0.0.0.0
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["omnimcp-server"]
