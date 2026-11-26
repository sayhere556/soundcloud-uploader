FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCM_DATA_DIR=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home uploader \
    && mkdir /data

COPY requirements-web.lock ./
RUN pip install --no-cache-dir -r requirements-web.lock

COPY --chown=uploader:uploader sc.py ./

RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -eu' \
    'if [ "$(id -u)" = "0" ]; then' \
    '  mkdir -p "$SCM_DATA_DIR"' \
    '  chown -R uploader:uploader "$SCM_DATA_DIR"' \
    '  chmod 700 "$SCM_DATA_DIR"' \
    '  exec gosu uploader "$@"' \
    'fi' \
    'exec "$@"' \
    > /usr/local/bin/entrypoint \
    && chmod 755 /usr/local/bin/entrypoint

EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/health')"

ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["python", "sc.py", "web", "--host", "0.0.0.0", "--port", "8085"]
