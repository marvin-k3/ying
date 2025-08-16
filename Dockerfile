# Dockerfile for Ying RTSP Music Tagger
FROM python:3.12-slim

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libchromaprint-tools \
        curl \
        build-essential \
        gcc \
        g++ \
        clang \
    && rm -rf /var/lib/apt/lists/*

# Install Rye
ENV RYE_HOME="/opt/rye"
ENV PATH="$RYE_HOME/shims:$PATH"
RUN curl -sSf https://rye.astral.sh/get | RYE_INSTALL_OPTION="--yes" bash && \
    rye config --set-bool behavior.use-uv=true

WORKDIR /app

# Copy project configuration first for better caching
COPY pyproject.toml .python-version README.md ./
COPY requirements*.lock ./

# Sync dependencies (production only for security)
RUN rye sync --no-dev

# Copy source code
COPY app ./app

# Create data directory and non-root user for security
RUN useradd -m appuser && \
    mkdir -p /data && \
    chown -R appuser:appuser /data /app

# Switch to non-root user
USER appuser

# Environment variables
ENV DB_PATH=/data/plays.db \
    PORT=44100 \
    TZ=America/Los_Angeles \
    PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:44100/internal/healthz || exit 1

# Expose port
EXPOSE 44100

# Volume for persistent data
VOLUME ["/data"]

# Run the application
CMD ["rye", "run", "serve"]
