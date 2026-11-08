# API image: FastAPI + LangGraph agent, also used for migrations and the seed.
# Build from the repository root (docker compose build api).
#
# Two stages: dependencies are installed into a virtual environment in a builder stage;
# the runtime stage copies only that environment and the application files and runs as a
# non-root user.

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
COPY pyproject.toml README.md docker/constraints.txt ./
COPY app ./app
RUN pip install -c constraints.txt . \
    && find /opt/venv -type d -name "__pycache__" -prune -exec rm -rf {} + \
    && find /opt/venv -type d \( -name "tests" -o -name "test" \) -path "*/site-packages/*" -prune -exec rm -rf {} +

FROM python:3.12-slim AS run
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    APP_ENV=production \
    API_HOST=0.0.0.0
RUN useradd --system --uid 10001 --no-create-home api
WORKDIR /srv/app
COPY --from=build /opt/venv /opt/venv
COPY app ./app
COPY config ./config
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini pyproject.toml ./
COPY data/northwind/northwind.sql data/northwind/LICENSE ./data/northwind/
# The evaluation set and its expected results (Admin > Evaluation).
COPY eval/cases.yaml ./eval/
COPY eval/expected ./eval/expected
COPY docker/api-entrypoint.sh /usr/local/bin/api-entrypoint
RUN chmod 0755 /usr/local/bin/api-entrypoint
USER api

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["api-entrypoint"]
CMD ["python", "scripts/run_api.py"]
