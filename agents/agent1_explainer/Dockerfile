FROM python:3.12-slim-bookworm

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy shared infrastructure and MCP server first (for layer caching)
COPY agents/shared/ /app/agents/shared/
COPY agents/mcp_server/ /app/agents/mcp_server/
COPY agents/__init__.py /app/agents/__init__.py

# Copy agent code
COPY agents/agent1_explainer/ /app/agents/agent1_explainer/

# Install dependencies
COPY agents/agent1_explainer/pyproject.toml /app/pyproject.toml
COPY agents/agent1_explainer/uv.lock /app/uv.lock
RUN uv sync --no-dev

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "agents.agent1_explainer.main:app", "--host", "0.0.0.0", "--port", "8001"]
