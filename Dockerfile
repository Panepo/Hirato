FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml requirements.txt ./

# Install dependencies using uv (into the system Python, no venv)
RUN uv pip install --system -r requirements.txt

# Copy application source
COPY main.py ./
COPY app/ ./app/
COPY static/ ./static/

# Persistent storage volumes
VOLUME ["/app/chroma_db", "/app/sessions.db"]

EXPOSE 7950

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7950"]
