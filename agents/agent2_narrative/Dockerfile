FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy shared infrastructure and MCP server first (for layer caching)
COPY agents/shared/ /app/agents/shared/
COPY agents/mcp_server/ /app/agents/mcp_server/
COPY agents/__init__.py /app/agents/__init__.py

# Copy agent code
COPY agents/agent2_narrative/ /app/agents/agent2_narrative/

# Install dependencies
COPY agents/agent2_narrative/pyproject.toml /app/pyproject.toml
RUN uv sync --no-dev

EXPOSE 8002

CMD ["uv", "run", "uvicorn", "agents.agent2_narrative.main:app", "--host", "0.0.0.0", "--port", "8002"]
