#!/bin/bash
set -e

# Start the LiveKit voice agent — force its internal health server to port 8081
# so it does NOT compete with uvicorn for $PORT.
python agent.py start --health-http-port 8081 &
AGENT_PID=$!

# Run the HTTP API server as the foreground process (Railway monitors this PID).
# If uvicorn exits, the container exits and Railway restarts it.
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
