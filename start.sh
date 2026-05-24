#!/bin/bash
set -e

# Ensure Python output is unbuffered so logs appear before a crash.
export PYTHONUNBUFFERED=1

# Start the LiveKit voice agent in the background.
# stderr is merged into stdout so Railway logs everything at the correct severity.
python agent.py start 2>&1 &
AGENT_PID=$!

# Run the HTTP API server as the foreground process (Railway monitors this PID).
# Merge uvicorn stderr → stdout so INFO lines aren't tagged as "error" by Railway.
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 2>&1
