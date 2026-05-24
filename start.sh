#!/bin/bash
set -e

# Unbuffered Python output — logs appear before a crash, not after.
export PYTHONUNBUFFERED=1

# Raise the file-descriptor limit for the whole container.
ulimit -n 65536 2>/dev/null || true

# ---------------------------------------------------------------------------
# Start the LiveKit voice agent with retry + exponential backoff.
# Railway already restarts the whole container on exit, but retrying here
# avoids a full cold-start for transient failures (network blip, slow model
# load, etc.).  After 3 failures we give up and let Railway do the restart.
# ---------------------------------------------------------------------------
start_agent() {
    local attempt=1
    local delay=5
    while [ $attempt -le 3 ]; do
        echo "[start.sh] Starting agent (attempt $attempt/3)..." >&1
        # Merge stderr → stdout so Railway tags logs by content, not fd.
        python agent.py start 2>&1 &
        AGENT_PID=$!

        # Give the agent a moment to crash fast vs. a real startup.
        sleep 3
        if kill -0 "$AGENT_PID" 2>/dev/null; then
            echo "[start.sh] Agent PID=$AGENT_PID is running" >&1
            return 0
        fi

        echo "[start.sh] Agent exited early on attempt $attempt; retrying in ${delay}s..." >&1
        attempt=$((attempt + 1))
        sleep $delay
        delay=$((delay * 2))
    done
    echo "[start.sh] Agent failed to start after 3 attempts; continuing without it" >&1
}

start_agent

# Run the HTTP API server as the foreground process (Railway monitors this PID).
# Merge stderr → stdout so INFO lines aren't tagged as "error" by Railway.
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 2>&1
