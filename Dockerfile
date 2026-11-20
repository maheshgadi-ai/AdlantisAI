# AdlantisAI: the app and command line in one image. Runs as a non-root user.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 10001 adlantis \
    && useradd --system --uid 10001 --gid adlantis --create-home adlantis

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples
RUN pip install ".[ui]" \
    && mkdir -p /app/outputs \
    && chown adlantis:adlantis /app/outputs

USER adlantis
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"

CMD ["adlantis", "demo", "--address", "0.0.0.0", "--port", "8501", "--headless"]
