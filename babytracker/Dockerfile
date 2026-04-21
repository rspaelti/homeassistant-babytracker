ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Europe/Zurich \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

RUN apk add --no-cache \
        tzdata \
        sqlite \
        curl \
        ca-certificates \
    && ln -sf /usr/share/zoneinfo/Europe/Zurich /etc/localtime \
    && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ /app/src/
COPY migrations/ /app/migrations/
COPY alembic.ini /app/
COPY scripts/ /app/scripts/
COPY data/ /app/data/
RUN uv sync --frozen --no-dev

COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
