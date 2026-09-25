FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "agent_core.api:app", "--host", "0.0.0.0", "--port", "8000"]
