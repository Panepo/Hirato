FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml requirements.txt ./

# Install dependencies using uv (into the system Python, no venv)
RUN uv pip install --system -r requirements.txt

# Install Node.js for Vue frontend build
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

COPY main.py ./
COPY app/ ./app/
COPY frontend/ ./frontend/
COPY static/ ./static/

# Build Vue frontend
RUN cd frontend && npm install && npm run build

# Persistent storage volumes
RUN mkdir -p /app/data
VOLUME ["/app/lancedb_db", "/app/data"]

EXPOSE 7950

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7950"]
