# Maya — Malaysian Multilingual Voice Receptionist

A voice AI receptionist that handles appointments, cancellations, rescheduling, FAQs, and human transfer across 4 languages: English, Bahasa Melayu, Tamil, and Mandarin.

---

## Stack

| Component | Provider | Model / Voice |
|-----------|----------|--------------|
| STT | ElevenLabs | Scribe v2 Realtime — auto-detects all 4 languages |
| TTS | ElevenLabs | eleven_multilingual_v2 — separate voice per language |
| LLM | Groq | llama-3.3-70b-versatile |
| VAD | Silero | Built into livekit-plugins-silero |
| Database | Supabase | contacts, bookings, voice_sessions, availability_slots |
| Voice infra | LiveKit | Agents v1.3.x |

---

## Project Files

```
VoiceAI/
├── agent.py              # Main agent — MayaAgent, tts_node, function tools
├── booking_manager.py    # Book / cancel / reschedule / FAQ logic
├── database.py           # Supabase wrappers
├── config.py             # All env vars loaded here
├── language_handler.py   # Text-based language detection (en/ms/ta/zh)
├── google_calendar.py    # Google Calendar (optional — needs google_token.json)
├── setup_google_auth.py  # Run once to generate google_token.json
├── tts_edge.py           # Edge TTS plugin (kept as fallback, not currently used)
├── requirements.txt
├── .env
└── INSTRUCTION.md
```

---

## Setup

### 1. Create virtual environment and install dependencies

```bash
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
pip install tzdata           # Windows only — needed for Asia/Kuala_Lumpur timezone
```

### 2. Configure `.env`

```env
# LiveKit
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# ElevenLabs — STT and TTS
ELEVENLABS_API_KEY=your_elevenlabs_api_key

# Groq — LLM
GROQ_API_KEY=your_groq_api_key

# Business config
TENANT_ID=your_tenant_uuid
BUSINESS_NAME=My Clinic
BUSINESS_HOURS_START=09:00
BUSINESS_HOURS_END=18:00
TIMEZONE=Asia/Kuala_Lumpur
BUSINESS_PHONE=
BUSINESS_ADDRESS=

# Google Calendar (optional — skip if not using)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_CALENDAR_ID=primary
GOOGLE_TOKEN_FILE=google_token.json
```

### 3. Run

```bash
python agent.py dev
```

Then open the LiveKit playground at https://cloud.livekit.io and connect to your project room to test.

---

## How Multilingual Works

### STT — ElevenLabs Scribe v2 Realtime
- No `language` lock — Scribe auto-detects English, Malay, Tamil, and Mandarin from the audio
- Previously used Groq Whisper with `language="en"` which mangled Malay/Tamil/Mandarin text completely, so language detection never fired and the voice never switched

### Language detection (text-based)
After Scribe transcribes the speech, `language_handler.py` reads the text and detects the language using Unicode script ranges (Tamil, CJK) and word lists (Malay/Manglish).

### TTS — ElevenLabs eleven_multilingual_v2
Four separate TTS instances, one per language, each with its own voice:

| Language | Voice ID |
|----------|----------|
| English | `kdmDKE6EkgrWrrykO9Qt` |
| Malay | `qAJVXEQ6QgjOQ25KuoU8` |
| Mandarin | `tOuLUAIdXShmWH7PEUrU` |
| Tamil | `mGboHvCVOXWYeFL8KTR0` |

The `tts_node` override in `MayaAgent` picks the right TTS instance based on `_detected_lang`.

### Language switching mid-call
When `on_user_turn_completed` detects a language change:
1. `_detected_lang` is updated
2. The system prompt is updated via `update_instructions(_build_prompt(new_lang))`
3. The next `tts_node` call automatically picks the new language's TTS instance

---

## Conversation Flow

Maya follows a strict one-question-per-turn rule enforced in the system prompt.

### Booking (9 turns)
1. Caller says they want an appointment → ask preferred date
2. Call `check_availability(YYYY-MM-DD)` → offer 2 time slots
3. Confirm which time
4. Ask service/reason for visit
5. Ask full name
6. If name unclear, ask spelling; read letters back: "So that's R-A-J-E-S-H — is that right?"
7. Ask phone number
8. Read back all details for confirmation
9. Call `book_appointment`

### Other tools
- `cancel_appointment` — find booking by phone, confirm, cancel
- `reschedule_appointment` — find booking, check new slot, reschedule
- `answer_faq` — hours, location, services, payment, parking
- `transfer_to_human` — escalate to staff (upset caller, medical emergency, billing)

### Date handling
System prompt injects today's date and tomorrow's date as YYYY-MM-DD at startup. LLM is instructed to always convert relative references ("tomorrow", "Friday") to YYYY-MM-DD before calling any tool.

### Name / phonetic confirmation
Step-by-step rules in the system prompt:
1. Ask name
2. If unsure, ask spelling next turn
3. Once spelled, read letters back one by one
4. Wait for confirmation before proceeding

---

## Echo / False Interruption Protection

Without headphones, the agent's speaker output can feed back into the microphone. Protections in place:

| Layer | Setting | Purpose |
|-------|---------|---------|
| Silero VAD | `activation_threshold=0.6` | Rejects faint echoes |
| Silero VAD | `min_speech_duration=0.15` | Catches real short words like "hi" |
| AgentSession | `min_interruption_words=2` | Needs 2+ words to count as interruption |
| AgentSession | `false_interruption_timeout=2.0` | Ignores brief noise during agent speech |
| `on_user_turn_completed` | garbage filter `len(words)<=1 and len(text)<6` | Drops single-word echo artifacts |

---

## Database Tables (Supabase)

### Existing tables (from your schema)
- `contacts` — phone, name, language_preference, tenant_id
- `bookings` — contact_id, scheduled_at (ISO 8601), service_type, status, gcal_event_id
- `voice_sessions` — livekit_room_id, contact_id, status, ended_at
- `call_logs` — transcript, language_detected, outcome, duration_sec, escalated

### New table (add this once)
```sql
CREATE TABLE availability_slots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    slot_date DATE NOT NULL,
    slot_time TIME NOT NULL,
    is_available BOOLEAN DEFAULT TRUE,
    UNIQUE(tenant_id, slot_date, slot_time)
);
```

Populate it with your clinic's open slots. The agent marks slots as taken when booking and frees them on cancel/reschedule. If the table is empty, `check_availability` will always return no slots — add rows first.

---

## Google Calendar (Optional)

Not required. If configured, bookings are also synced to Google Calendar.

1. Create a **Desktop app** OAuth2 client in Google Cloud Console
2. Enable Google Calendar API for the project
3. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to `.env`
4. Run once: `python setup_google_auth.py` — opens browser to authorise and saves `google_token.json`
5. Set `GOOGLE_CALENDAR_ID=primary` (or your calendar ID) in `.env`

If `google_token.json` is missing, the agent falls back to Supabase availability_slots only.

---

## Known Fixes Applied

### STT language lock removed
**Problem:** Groq Whisper `language="en"` was set to prevent echo misdetection. This worked but meant Malay/Tamil/Mandarin speech came out as garbled English text. Language detection never fired. Voice never switched.

**Fix:** Replaced Groq Whisper with ElevenLabs Scribe v2 Realtime. Scribe natively handles all 4 languages with auto-detection. No language lock needed.

### Mandarin routed to wrong TTS
**Problem:** `tts_node` only routed `ms` and `ta` to Edge TTS. Mandarin (`zh`) fell through to Cartesia (an English-only voice), producing silence or garbled audio.

**Fix:** Switched to ElevenLabs with a dedicated voice per language. All 4 languages handled by the same provider.

### Echo → "Obrigado" / auto-transfer
**Problem:** Without headphones, the agent's own voice triggered the microphone. Groq Whisper with auto-detect misidentified the echo as Portuguese ("Obrigado"), then the LLM transferred to human.

**Fix:** STT language lock (now replaced by Scribe), Silero VAD threshold 0.6, `min_interruption_words=2`, and garbage text filter.

### Two questions per turn
**Problem:** LLM was asking name and spelling in the same response.

**Fix:** Explicit step-by-step name rules in system prompt with one-question-per-turn constraint.

### Date format — "Friday" passed to tools
**Problem:** LLM was passing "Friday" or "tomorrow" as the date argument to `check_availability` instead of YYYY-MM-DD.

**Fix:** System prompt now injects `today_date` and `tomorrow_date` as YYYY-MM-DD and explicitly forbids passing day names to tools.

### Edge TTS abstract method error
**Problem:** `TypeError: Can't instantiate abstract class EdgeChunkedStream with abstract method _run`

**Fix:** LiveKit requires `_run(self, output_emitter: AudioEmitter)` not `_main_task`. Fixed in `tts_edge.py`. Edge TTS is kept in the repo but not currently used.

---

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && pip install tzdata
COPY . .
CMD ["python", "agent.py", "start"]
```

```bash
docker build -t maya-receptionist .
docker run --env-file .env maya-receptionist
```

### Railway / Fly.io

Set all `.env` variables as environment secrets and use start command `python agent.py start`.

---

## Troubleshooting

**Agent speaks but not responding to voice**
- VAD threshold may be too high. Try lowering `activation_threshold` to `0.5`.
- Check microphone permissions in browser.

**Language does not switch**
- Scribe transcription may not match expected language patterns. Log `text` in `on_user_turn_completed` to see what's coming through.
- Check `language_handler.py` word lists for Malay/Manglish.

**Booking always says no slots available**
- `availability_slots` table is empty. Insert rows for your clinic's open times.

**Google Calendar not syncing**
- Run `setup_google_auth.py` again to refresh `google_token.json`.
- Ensure Google Calendar API is enabled in your Google Cloud project.

**`ZoneInfoNotFoundError: Asia/Kuala_Lumpur`**
- Run `pip install tzdata` (Windows only — timezone data not built in).
