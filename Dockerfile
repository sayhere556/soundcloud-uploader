FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SCM_DATA_DIR=/data
WORKDIR /app
COPY requirements-web.lock ./
RUN pip install --no-cache-dir -r requirements-web.lock \
    && useradd --uid 10001 --create-home manager \
    && mkdir /data && chown manager:manager /data
COPY --chown=manager:manager manager.py ./
COPY --chown=manager:manager sc_manager ./sc_manager
USER manager
EXPOSE 8085
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/health')"
CMD ["python", "manager.py", "web", "--host", "0.0.0.0", "--port", "8085"]
