# Maya Voice Backend

Malaysian AI voice receptionist using LiveKit + Groq Kimi K2 + ElevenLabs.

## Architecture

Two Railway services for crash isolation:
- **maya-api**: FastAPI REST server (issues tokens, serves call logs)
- **maya-worker**: LiveKit agent (STT → LLM → TTS pipeline)

## Stack
- **LLM**: moonshotai/kimi-k2-instruct-0905 (256K context, excellent multilingual tool use)
- **STT**: Groq whisper-large-v3-turbo
- **TTS**: ElevenLabs eleven_turbo_v2_5
- **Database**: Shared Supabase with WhatsApp agent
- **Deploy**: Railway (2 independent services)

## Local Development

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Create .env from .env.example and fill in keys

# Terminal 1 - API
uvicorn main:app --reload --port 8000

# Terminal 2 - Worker
python worker.py dev
```

## Deploy

Railway auto-deploys on push to main.

Services:
- `maya-api`: Uses `Dockerfile.api`
- `maya-worker`: Uses `Dockerfile.worker`

Both must have identical environment variables set in Railway.

## Test

```bash
# API health
curl https://maya-api.up.railway.app/health
# Expected: {"status":"ok","service":"maya-api"}

# Agent health
curl https://maya-api.up.railway.app/api/health
# Expected: {"maya":"online","model":"moonshotai/kimi-k2-instruct-0905"}

# Get token
curl -X POST https://maya-api.up.railway.app/api/token \
  -H "Content-Type: application/json" \
  -d '{"room_name":"test","language":"en"}'
# Expected: {"token":"eyJ...","url":"wss://..."}
```

## Troubleshooting

| Issue | Check |
|---|---|
| API 500 errors | Railway `maya-api` logs, verify env vars |
| Worker not joining calls | Railway `maya-worker` logs, verify `LIVEKIT_*` vars |
| No audio from Maya | Check `ELEVENLABS_VOICE_ID` is exact UUID |
| Kimi K2 model errors | Test access in Groq playground first |
