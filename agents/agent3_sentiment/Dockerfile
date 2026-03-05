FROM python:3.12-slim

# Install Azure CLI (for AzureCliCredential in local dev)
RUN apt-get update && apt-get install -y curl && \
    curl -sL https://aka.ms/InstallAzureCLIDeb | bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy shared infrastructure first (for layer caching)
COPY agents/shared/ /app/agents/shared/
COPY agents/__init__.py /app/agents/__init__.py

# Copy agent code
COPY agents/agent3_sentiment/ /app/agents/agent3_sentiment/

# Install dependencies
COPY agents/agent3_sentiment/pyproject.toml /app/pyproject.toml
RUN uv sync --no-dev

EXPOSE 8003

CMD ["uv", "run", "uvicorn", "agents.agent3_sentiment.main:app", "--host", "0.0.0.0", "--port", "8003"]
