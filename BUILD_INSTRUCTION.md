# BUILD_INSTRUCTION.md — Maya Voice Backend (2-Service Architecture)

**For Antigravity/Claude Code execution. This builds Maya's backend with proper service separation for crash isolation.**

---

## Architecture

```
Railway Project: maya-voice
├── maya-api       ← FastAPI REST server only
└── maya-worker    ← LiveKit agent only (connects outbound to LiveKit)
```

**Why split?**
- If the worker crashes (agent bug), API stays up — dashboard still works
- If API crashes (HTTP error), worker stays up — active calls continue
- Independent logs, independent health checks, independent scaling

---

## Prerequisites (MUST DO BEFORE RUNNING THIS INSTRUCTION)

### 1. Create Railway Project with TWO services

**In Railway:**

1. Go to railway.app → **New Project** → **Empty Project**
2. Name it: `maya-voice`

**Add Service 1 — maya-api:**
1. Click **+ New Service** → **GitHub Repo**
2. Configure GitHub App if needed → select your `maya-voice` repo
3. Service name: `maya-api`
4. **Settings → Source:**
   - Root Directory: `backend`
   - Dockerfile Path: `backend/Dockerfile.api`
5. **Settings → Networking:**
   - Generate Domain → **copy this URL** (you'll need it for frontend)

**Add Service 2 — maya-worker:**
1. Click **+ New Service** → **GitHub Repo** → select `maya-voice` repo again
2. Service name: `maya-worker`
3. **Settings → Source:**
   - Root Directory: `backend`
   - Dockerfile Path: `backend/Dockerfile.worker`
4. No domain needed (worker connects outbound only)

---

### 2. Set Environment Variables (on BOTH services)

**In Railway → each service → Variables tab, add these:**

```
SUPABASE_URL=https://pfsmmlmmrnttbbdhacgk.supabase.co
SUPABASE_SERVICE_KEY=(Supabase → Settings → API → service_role secret key)

LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxx
LIVEKIT_API_SECRET=(LiveKit Cloud → Keys)

GROQ_API_KEY=gsk_...
ELEVENLABS_API_KEY=(ElevenLabs → Profile → API Key)
ELEVENLABS_VOICE_ID=(ElevenLabs → Voices → copy voice UUID)

CARTESIA_API_KEY=
GOOGLE_API_KEY=
```

**Tip:** Set vars on `maya-api` first, then on `maya-worker` click **Raw Editor** and paste the same block.

---

### 3. Get API Keys (if you don't have them yet)

| Service | Where | What to copy |
|---|---|---|
| **LiveKit** | cloud.livekit.io → new project | WebSocket URL, API Key, Secret |
| **Groq** | console.groq.com → API Keys | API key (gsk_...) |
| **ElevenLabs** | elevenlabs.io → Voices | Pick a voice → copy Voice ID (UUID) |
| **ElevenLabs** | elevenlabs.io → Profile | API Key |
| **Supabase** | Your existing project | Project URL, service_role key |

**Test Groq access to Kimi K2:**
- Go to console.groq.com/playground
- Select model: `moonshotai/kimi-k2-instruct-0905`
- Send test message — if it works, you have access

---

### 4. Run Supabase Migration (one-time)

**In Supabase → SQL Editor → New Query → paste and run:**

```sql
-- Add voice columns to call_logs
ALTER TABLE call_logs
  ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'voice',
  ADD COLUMN IF NOT EXISTS livekit_room_id TEXT,
  ADD COLUMN IF NOT EXISTS duration_sec INTEGER,
  ADD COLUMN IF NOT EXISTS transcript TEXT,
  ADD COLUMN IF NOT EXISTS sentiment TEXT,
  ADD COLUMN IF NOT EXISTS escalated BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS language_used TEXT;

-- New voice_sessions table
CREATE TABLE IF NOT EXISTS voice_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  contact_id UUID REFERENCES contacts(id),
  livekit_room_id TEXT NOT NULL UNIQUE,
  status TEXT DEFAULT 'active',
  started_at TIMESTAMPTZ DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  call_log_id UUID REFERENCES call_logs(id),
  metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_voice_sessions_tenant
  ON voice_sessions(tenant_id, started_at DESC);

-- Add voice config to tenant_settings
ALTER TABLE tenant_settings
  ADD COLUMN IF NOT EXISTS voice_enabled BOOLEAN DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS voice_provider TEXT DEFAULT 'elevenlabs',
  ADD COLUMN IF NOT EXISTS voice_id TEXT,
  ADD COLUMN IF NOT EXISTS voice_model TEXT DEFAULT 'moonshotai/kimi-k2-instruct-0905',
  ADD COLUMN IF NOT EXISTS voice_greeting_ms TEXT DEFAULT 'Selamat datang! Saya Maya. Boleh saya bantu anda?',
  ADD COLUMN IF NOT EXISTS voice_greeting_en TEXT DEFAULT 'Welcome! I''m Maya. How can I help you today?',
  ADD COLUMN IF NOT EXISTS voice_greeting_zh TEXT DEFAULT '欢迎！我是Maya。请问有什么可以帮您？',
  ADD COLUMN IF NOT EXISTS voice_greeting_ta TEXT DEFAULT 'வணக்கம்! நான் Maya. உங்களுக்கு எப்படி உதவ முடியும்?',
  ADD COLUMN IF NOT EXISTS max_call_duration_sec INTEGER DEFAULT 300;

-- RLS policies
ALTER TABLE voice_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service role full access" ON voice_sessions FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "anon read" ON voice_sessions FOR SELECT USING (true);

-- Seed default config
INSERT INTO tenant_settings (tenant_id)
SELECT id FROM tenants LIMIT 1
ON CONFLICT DO NOTHING;
```

Should complete with no errors. Verify: **Table Editor** → `voice_sessions` exists.

---

## EXECUTE — Build the Backend

Antigravity will execute all steps below. Just paste the instruction and watch it go.

---

### Step 1 — Create folder structure

```bash
mkdir -p backend/agent backend/api
touch backend/agent/__init__.py backend/api/__init__.py
```

---

### Step 2 — `backend/requirements.txt`

```txt
livekit-agents[groq,elevenlabs,cartesia,silero,openai]~=1.5
fastapi==0.115.0
uvicorn[standard]==0.30.6
supabase==2.9.0
python-dotenv==1.0.1
pydantic==2.8.2
pydantic-settings==2.4.0
httpx==0.27.2
```

---

### Step 3 — `backend/.gitignore`

```
.env
.venv/
__pycache__/
*.pyc
*.egg-info/
dist/
```

---

### Step 4 — `backend/.env.example`

```env
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

GROQ_API_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=

CARTESIA_API_KEY=
GOOGLE_API_KEY=
```

---

### Step 5 — `backend/agent/config_loader.py`

```python
from supabase import create_client, Client
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    groq_api_key: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str = ""
    cartesia_api_key: str = ""
    google_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
_supabase: Client = create_client(settings.supabase_url, settings.supabase_service_key)


def get_supabase() -> Client:
    return _supabase


def load_tenant_config(tenant_id: str) -> dict:
    try:
        resp = (
            _supabase.table("tenant_settings")
            .select("*")
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        return resp.data or {}
    except Exception:
        return {}


def get_system_prompt(tenant_id: str, language: str = "en") -> str:
    config = load_tenant_config(tenant_id)
    base_prompt = config.get(
        "system_prompt",
        "You are Maya, a friendly and professional AI receptionist."
    )
    lang_map = {
        "ms": "Respond primarily in Bahasa Malaysia. Switch if caller switches.",
        "en": "Respond primarily in English. Switch if caller switches.",
        "zh": "Respond primarily in Mandarin Chinese. Switch if caller switches.",
        "ta": "Respond primarily in Tamil. Switch if caller switches.",
    }
    lang_instruction = lang_map.get(language, "Match the caller's language.")
    return (
        f"{base_prompt}\n\n"
        f"{lang_instruction}\n\n"
        "VOICE RULES:\n"
        "- Keep responses under 35 words. This is voice, not chat.\n"
        "- Never use markdown, bullets, or emojis.\n"
        "- Spell out numbers: 'three PM' not '3 PM'.\n"
        "- Ask ONE question at a time.\n"
        "- If you cannot help, say so and offer to transfer."
    )
```

---

### Step 6 — `backend/agent/tools.py`

```python
from livekit.agents import function_tool, RunContext
from agent.config_loader import get_supabase


def get_tool_definitions(tenant_id: str) -> list:
    db = get_supabase()

    @function_tool
    async def check_availability(
        context: RunContext,
        date: str,
        time_slot: str,
        service: str = "General",
    ) -> str:
        """Check if a date/time is available for booking.

        Args:
            date: Date in YYYY-MM-DD
            time_slot: Time in HH:MM 24-hour format
            service: Service type
        """
        resp = (
            db.table("bookings")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("booking_date", date)
            .eq("booking_time", time_slot)
            .eq("status", "confirmed")
            .execute()
        )
        if resp.data:
            return f"Sorry, {date} at {time_slot} is taken. Different time?"
        return f"{date} at {time_slot} is available. Book it?"

    @function_tool
    async def create_booking(
        context: RunContext,
        name: str,
        phone: str,
        date: str,
        time_slot: str,
        service: str = "General",
        notes: str = "",
    ) -> str:
        """Create a booking.

        Args:
            name: Full name
            phone: Phone number
            date: YYYY-MM-DD
            time_slot: HH:MM 24-hour
            service: Service type
            notes: Special requests
        """
        contact_resp = (
            db.table("contacts")
            .upsert(
                {"tenant_id": tenant_id, "phone": phone, "name": name},
                on_conflict="tenant_id,phone",
            )
            .execute()
        )
        contact_id = contact_resp.data[0]["id"] if contact_resp.data else None

        db.table("bookings").insert({
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "booking_date": date,
            "booking_time": time_slot,
            "service": service,
            "notes": notes,
            "status": "confirmed",
            "source": "voice",
        }).execute()
        return f"Confirmed for {name} on {date} at {time_slot}."

    @function_tool
    async def lookup_booking(context: RunContext, phone: str) -> str:
        """Look up bookings by phone.

        Args:
            phone: Phone number
        """
        resp = (
            db.table("bookings")
            .select("booking_date, booking_time, service, status")
            .eq("tenant_id", tenant_id)
            .order("booking_date", desc=True)
            .limit(3)
            .execute()
        )
        if not resp.data:
            return "No bookings found. Make a new one?"
        results = "; ".join(
            f"{r['service']} on {r['booking_date']} at {r['booking_time']} ({r['status']})"
            for r in resp.data
        )
        return f"Recent bookings: {results}."

    return [check_availability, create_booking, lookup_booking]
```

---

### Step 7 — `backend/agent/maya_agent.py`

```python
import logging
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    RoomInputOptions,
    cli,
)
from livekit.plugins import groq, elevenlabs, silero

from agent.config_loader import settings, get_system_prompt, load_tenant_config, get_supabase
from agent.tools import get_tool_definitions

logger = logging.getLogger("maya")
DEFAULT_TENANT_ID = "default"


def prewarm(proc):
    """Load Silero VAD at worker startup."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    tenant_id = DEFAULT_TENANT_ID
    language = "en"
    for part in (ctx.room.metadata or "").split(","):
        k, _, v = part.partition("=")
        if k.strip() == "tenant_id" and v.strip():
            tenant_id = v.strip()
        if k.strip() == "language" and v.strip():
            language = v.strip()

    config = load_tenant_config(tenant_id)
    system_prompt = get_system_prompt(tenant_id, language)
    greeting = config.get(
        f"voice_greeting_{language}",
        "Hello! I'm Maya. How can I help?"
    )

    db = get_supabase()
    db.table("voice_sessions").insert({
        "tenant_id": tenant_id,
        "livekit_room_id": ctx.room.name,
        "status": "active",
    }).execute()

    llm_model = config.get("voice_model", "moonshotai/kimi-k2-instruct-0905")

    agent = Agent(
        instructions=system_prompt,
        tools=get_tool_definitions(tenant_id),
        llm=groq.LLM(api_key=settings.groq_api_key, model=llm_model),
        stt=groq.STT(
            api_key=settings.groq_api_key,
            model="whisper-large-v3-turbo",
            language=language,
            detect_language=True,
        ),
        tts=elevenlabs.TTS(
            api_key=settings.elevenlabs_api_key,
            voice_id=config.get("voice_id") or settings.elevenlabs_voice_id,
            model="eleven_turbo_v2_5",
        ),
    )

    session = AgentSession(vad=ctx.proc.userdata.get("vad") or silero.VAD.load())
    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(auto_subscribe=True),
    )
    await session.say(greeting, allow_interruptions=True)

    await ctx.wait_for_disconnect()

    db.table("voice_sessions").update(
        {"status": "ended", "ended_at": "now()"}
    ).eq("livekit_room_id", ctx.room.name).execute()
    logger.info("Call ended: %s", ctx.room.name)
```

---

### Step 8 — `backend/api/routes.py`

```python
from fastapi import APIRouter
from livekit import api as lkapi
from pydantic import BaseModel
from agent.config_loader import settings, get_supabase

router = APIRouter()


class TokenRequest(BaseModel):
    room_name: str
    participant_name: str = "caller"
    tenant_id: str = "default"
    language: str = "en"


@router.post("/token")
async def get_token(req: TokenRequest):
    """Issue LiveKit access token for browser caller."""
    token = (
        lkapi.AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        .with_identity(req.participant_name)
        .with_name(req.participant_name)
        .with_grants(lkapi.VideoGrants(room_join=True, room=req.room_name))
        .with_metadata(f"tenant_id={req.tenant_id},language={req.language}")
    )
    return {"token": token.to_jwt(), "url": settings.livekit_url}


@router.get("/calls")
async def list_calls(tenant_id: str = "default", limit: int = 20):
    """List recent voice call sessions."""
    db = get_supabase()
    resp = (
        db.table("voice_sessions")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data


@router.get("/health")
async def health():
    return {"maya": "online", "model": "moonshotai/kimi-k2-instruct-0905"}
```

---

### Step 9 — `backend/main.py`

```python
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Maya Voice API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your Vercel domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health")
async def root_health():
    return {"status": "ok", "service": "maya-api"}
```

---

### Step 10 — `backend/worker.py`

```python
"""LiveKit agent worker entrypoint — runs as separate Railway service."""
from livekit.agents import WorkerOptions, cli
from agent.maya_agent import entrypoint, prewarm

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
```

---

### Step 11 — `backend/Dockerfile.api` (for maya-api service)

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### Step 12 — `backend/Dockerfile.worker` (for maya-worker service)

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .

# CPU-only torch for Silero VAD (no GPU needed)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-download Silero model at build time (prevents cold start)
RUN python -c "from livekit.plugins import silero; silero.VAD.load()"

CMD ["python", "worker.py", "start"]
```

---

### Step 13 — `README.md`

```markdown
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
```

---

### Step 14 — Commit and push

```bash
git add .
git commit -m "feat: Maya voice backend - 2-service architecture for crash isolation"
git push origin main
```

---

## After Pushing

Railway auto-deploys both services. Monitor:

**maya-api:**
1. Railway → `maya-api` → Deployments → latest → Build Logs
2. Look for: `Application started on port 8000`
3. Test: `curl https://YOUR-DOMAIN/health`

**maya-worker:**
1. Railway → `maya-worker` → Deployments → latest → Logs
2. Look for: `Starting worker` and `Connected to LiveKit`
3. No errors in last 30 lines = good

---

## Verification Checklist

```
RAILWAY SETUP
[ ] maya-api service created with Dockerfile.api
[ ] maya-worker service created with Dockerfile.worker
[ ] Both have identical env vars set
[ ] maya-api has public domain generated

DEPLOYMENT
[ ] Both services show green "Active" status
[ ] maya-api logs show "Application started"
[ ] maya-worker logs show "Starting worker"

API TESTS
[ ] curl /health → {"status":"ok","service":"maya-api"}
[ ] curl /api/health → {"maya":"online",...}
[ ] curl /api/token POST → returns token + url

DATABASE
[ ] voice_sessions table exists in Supabase
[ ] tenant_settings has voice_* columns
```

---

## Next Steps

Add frontend to your existing `YourReceptionist/frontend/` project:
- `app/voice/test-call/page.tsx` — browser call tester
- `app/voice/calls/page.tsx` — call logs
- `components/CallTester.tsx` — LiveKit UI component
- `lib/livekit.ts` — token fetching

Frontend instruction available separately if needed.
