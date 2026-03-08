FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY main.py .
COPY postgres_handler.py .
COPY cosmos_handler.py .
COPY eventhub_handler.py .

ENTRYPOINT ["uv", "run", "python", "main.py"]
