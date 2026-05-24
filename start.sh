#!/bin/bash
set -e

# Start the HTTP API server (token generation, webhooks, bookings)
uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 &
API_PID=$!

# Start the LiveKit voice agent
python agent.py start &
AGENT_PID=$!

# Exit if either process dies — Railway will restart the container
wait -n $API_PID $AGENT_PID
EXIT_CODE=$?
kill $API_PID $AGENT_PID 2>/dev/null || true
exit $EXIT_CODE
