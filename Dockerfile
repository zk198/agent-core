FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock* ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"
EXPOSE 8000
CMD ["uvicorn", "agent_core.api:app", "--host", "0.0.0.0", "--port", "8000"]
