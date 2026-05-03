FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY privatelabbench ./privatelabbench
COPY configs ./configs
COPY examples ./examples
COPY docs ./docs

RUN python -m pip install --upgrade pip && \
    pip install -e '.[api]'

RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/reports /data /app/.privatelabbench_api/runs && \
    chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import os, urllib.request; port=os.getenv('PRIVATELABBENCH_HEALTH_PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2).read()"

ENTRYPOINT ["privatelabbench"]
CMD ["--help"]
