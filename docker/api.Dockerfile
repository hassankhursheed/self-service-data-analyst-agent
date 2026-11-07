# API image: FastAPI + LangGraph agent. Build from the repository root:
#   docker compose build api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

COPY pyproject.toml README.md docker/constraints.txt ./
COPY app ./app
RUN pip install -c constraints.txt .

COPY config ./config
COPY scripts ./scripts
COPY docker/api-entrypoint.sh /usr/local/bin/api-entrypoint
RUN chmod 0755 /usr/local/bin/api-entrypoint \
    && useradd --system --uid 10001 --no-create-home api
USER api

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["api-entrypoint"]
CMD ["python", "scripts/run_api.py", "--host", "0.0.0.0", "--port", "8000"]
