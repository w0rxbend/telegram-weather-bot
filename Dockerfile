# ---- builder: turn poetry.lock into a pinned requirements.txt ------------------------------
FROM python:3.14-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_NO_INTERACTION=1

RUN pip install "poetry>=2.0,<3" poetry-plugin-export

WORKDIR /build
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --without-hashes -o requirements.txt


# ---- runtime -------------------------------------------------------------------------------
FROM python:3.14-slim

# Unbuffered logs, no .pyc clutter, state in a mountable volume.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    PYTHONPATH=/app/src

RUN addgroup --gid 1000 userapp \
    && adduser --home /home/userapp --gid 1000 --uid 1000 --disabled-password userapp \
    && mkdir -p /data && chown userapp:userapp /data

WORKDIR /app
COPY --from=builder /build/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY src/ ./src

USER userapp
VOLUME ["/data"]

# Healthy while the scheduler loop keeps touching DATA_DIR/heartbeat (see weather_bot.health).
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-m", "weather_bot.health"]

CMD ["python", "-m", "weather_bot"]
