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
    pip install -e .

RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/reports /data && \
    chown -R appuser:appuser /app /data

USER appuser

ENTRYPOINT ["privatelabbench"]
CMD ["--help"]
