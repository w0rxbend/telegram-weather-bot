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
# pip is not needed at runtime, and its vendored copies of certifi, urllib3, msgpack and
# setuptools are what the Trivy gate in docker-ci.yml flags; drop it once the deps are in.
RUN pip install -r requirements.txt \
    && pip uninstall -y pip

COPY src/ ./src

USER userapp
VOLUME ["/data"]

# Healthy while the scheduler loop keeps touching DATA_DIR/heartbeat (see weather_bot.health).
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-m", "weather_bot.health"]

CMD ["python", "-m", "weather_bot"]
