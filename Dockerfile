FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SCM_DATA_DIR=/data
WORKDIR /app
COPY requirements-web.lock ./
RUN pip install --no-cache-dir -r requirements-web.lock \
    && useradd --uid 10001 --create-home uploader \
    && mkdir /data && chown uploader:uploader /data
COPY --chown=uploader:uploader sc.py ./
USER uploader
EXPOSE 8085
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/health')"
CMD ["python", "sc.py", "web", "--host", "0.0.0.0", "--port", "8085"]
