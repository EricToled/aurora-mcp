# AURORA MCP server — remote (HTTP) deployment image.
# Runs the SAME deterministic gate code as local stdio, served over HTTP so
# it can be registered as a custom connector and reached from any Claude
# session (Cowork or regular).
FROM python:3.13-slim

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Project source + the package metadata, then editable install.
COPY pyproject.toml ./
COPY src ./src
COPY schema ./schema
COPY templates ./templates
COPY platform_capabilities ./platform_capabilities
RUN pip install --no-cache-dir -e .

# SQLite audit DB path (ephemeral on free tier; override with a volume on paid).
ENV AURORA_DB_PATH=/app/aurora.db
ENV AURORA_HTTP=1
# Render/most PaaS inject PORT; default to 8000 for local docker run.
ENV PORT=8000
EXPOSE 8000

# The MCP endpoint is served at /mcp.
CMD ["python", "-m", "aurora.server", "--http"]
