FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /src
COPY packages ./packages
RUN uv pip install --system --no-sources \
    ./packages/goatbeat-core ./packages/goatbeat-cli ./packages/goatbeat \
    ./packages/goatbeat-postgres ./packages/goatbeat-rq "psycopg[binary]"

WORKDIR /app
COPY examples/distributed/demo ./demo
ENV PYTHONPATH=/app GOATBEAT_APP=demo.beat:app
