FROM python:3.12-slim

WORKDIR /app

# System deps for audio/ML packages
# libgomp1 is required by PyTorch (OpenMP runtime); missing from python:slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only torch first to avoid pulling the ~700 MB CUDA wheel
# (the default Linux PyPI wheel includes CUDA and often causes OOM/timeout in CI)
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download livekit ML model files (turn detector, VAD, etc.) into the image
# so they are available immediately at runtime without network delay.
RUN python -m livekit.agents download-files

# Copy application code
COPY . .

# Start both the HTTP API server (uvicorn) and the LiveKit voice agent.
# The agent health server is forced to port 8081 so it does not conflict
# with uvicorn which binds to $PORT (Railway's routable port).
CMD ["bash", "start.sh"]
