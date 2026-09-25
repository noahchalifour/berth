# syntax=docker/dockerfile:1.7
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" \
    HUB_DB_PATH=/data/hub.db
RUN useradd --system --uid 10011 --no-create-home hub && mkdir -p /data && chown hub:hub /data
USER 10011
EXPOSE 8080 8081
CMD ["emulator-hub"]
