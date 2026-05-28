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
        python agent.py start 2>&1 &
        AGENT_PID=$!

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
    echo "[start.sh] Agent failed to start after 3 attempts; exiting so Railway restarts the container" >&1
    exit 1
}

start_agent

# Watch the agent in the background — if it dies, kill the container so
# Railway restarts it. Without this, uvicorn keeps running with no agent.
watch_agent() {
    while kill -0 "$AGENT_PID" 2>/dev/null; do
        sleep 10
    done
    echo "[start.sh] Agent PID=$AGENT_PID died; killing container for Railway restart" >&1
    kill $UVICORN_PID 2>/dev/null
    exit 1
}
watch_agent &

# Run the HTTP API server as the foreground process (Railway monitors this PID).
uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 2>&1 &
UVICORN_PID=$!
wait $UVICORN_PID
