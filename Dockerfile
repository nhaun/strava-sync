FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WATCH_DIR=/watch \
    STATE_DIR=/state

WORKDIR /app
COPY pyproject.toml ./
COPY strava_sync ./strava_sync
RUN pip install . \
    && useradd --uid 1000 --create-home app \
    && mkdir -p /watch /state \
    && chown app:app /watch /state

USER app
VOLUME ["/state"]

HEALTHCHECK --interval=5m --timeout=10s --start-period=15m --retries=1 \
    CMD sh -c 'grep -q "^OK" "${STATE_DIR}/health"'

CMD ["strava-sync"]
