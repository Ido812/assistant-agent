# =============================================================
# Dockerfile for Assistant Agent
#
# Multi-stage build:
#   Stage 1: Build the React frontend (produces static HTML/CSS/JS)
#   Stage 2: Python runtime with FastAPI + the built frontend
#
# Build (run from project root):
#   docker build -f web/Dockerfile -t assistant-agent .
# Run:
#   docker run -p 8080:8080 --env-file .env \
#     -v $(pwd)/data:/app/data \
#     -v $(pwd)/credentials.json:/app/credentials.json:ro \
#     -v $(pwd)/token.json:/app/token.json \
#     assistant-agent
# =============================================================

# --- Stage 1: Build React frontend ---
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci
COPY web/frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.11-slim
WORKDIR /app

# Install Python dependencies (both existing + web server)
COPY requirements.txt web/requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

# Copy application code
COPY main.py ./
COPY web/server.py ./
COPY agents/ agents/
COPY mcp_servers/ mcp_servers/

# Copy the built frontend from Stage 1
# Put it next to server.py so _FRONTEND_DIR resolves correctly
COPY --from=frontend-build /app/frontend/dist frontend/dist/

# Create data directories (mounted as volume in production)
RUN mkdir -p data/memory

# Cloud Run uses PORT env var (default 8080)
EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
