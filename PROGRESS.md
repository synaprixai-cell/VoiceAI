# Maya Production Implementation Progress

**Started:** 2026-05-21
**Target completion:** 2026-05-22
**Status:** 8/10 tasks completed (80%)

---

## Week 1: Critical Issues (MUST DO) ⏰

### Task 1: Fallback Adapters ✅
- [x] 1.1 Add FallbackAdapter for STT — ElevenLabs Scribe → Deepgram Nova-3 → Groq Whisper
- [x] 1.2 Add FallbackAdapter for LLM — Groq llama-3.3-70b → Groq llama-3.1-8b-instant
- [x] 1.3 Add FallbackAdapter for TTS — ElevenLabs per-lang → EdgeTTS (try/except in tts_node)
- [x] 1.4 Add error recovery in session handler — tts_node retries fallback on exception
- [x] 1.5 Test fallback activation — tested via unit mocks and log_fallback hook

**Status:** Complete
**Notes:** Switched STT from Groq Whisper to ElevenLabs Scribe v2 Realtime for true multilingual support. `use_realtime=True` is the correct param (not `model=`).

---

### Task 2: Testing Framework ✅
- [x] 2.1 Create tests/conftest.py — AsyncMock fixtures for BookingManager, DB, LanguageHandler
- [x] 2.2 Create tests/test_maya_booking.py — booking, cancel, reschedule, FAQ, validation
- [x] 2.3 Write English booking test
- [x] 2.4 Write Malay booking test
- [x] 2.5 Write name spelling test
- [x] 2.6 Set up pytest + pytest-asyncio
- [x] 2.7 Create tests/test_maya_languages.py — 47 tests across both files, all passing

**Status:** Complete
**Notes:** Fixed `conftest import error` — conftest is auto-loaded by pytest, not directly importable. Fixed 2 tests that assumed lang detection returns non-None for ambiguous input (lang_handler returns None; caller falls back to `self._detected_lang`).

---

### Task 3: Observability ✅
- [x] 3.1 Create observability.py — PIIFilter, ContextFilter, _Metrics dataclass
- [x] 3.2 Structured logging — JSON-like format with room_id/job_id injected via ContextFilter
- [x] 3.3 Add metrics collection — timed() context manager records latency_ms per operation
- [x] 3.4 Add session/language/fallback/transfer helpers — log_session_start/end, log_language_switch, log_fallback, log_transfer
- [x] 3.5 Wired into agent.py — all helpers called in correct places

**Status:** Complete
**Notes:** PIIFilter scrubs phone [PHONE], NRIC [NRIC], email [EMAIL] from every log record.

---

## Week 2: High Priority (SHOULD DO) ⚠️

### Task 4: Security ✅
- [x] 4.1 Input validation — validate_phone (Malaysian regex), validate_date (YYYY-MM-DD, future, ≤90 days), validate_time (HH:MM), sanitize_name (unicode normalize, 100 char limit)
- [x] 4.2 Rate limiting — max 3 booking attempts/hour per phone (in-memory defaultdict)
- [x] 4.3 PII filtering — PIIFilter in observability.py applied to all log records
- [x] 4.4 Config security — removed Cartesia keys, added elevenlabs_api_key

**Status:** Complete

---

### Task 5: Performance ✅
- [x] 5.1 Supabase queries optimised — SELECT * replaced with specific columns
- [x] 5.2 FAQ caching — _FAQ_CACHE dict with 1-hour TTL using time.monotonic()
- [x] 5.3 Database indexes — sql/indexes.sql created with 6 indexes + conversation_states table
- [x] 5.4 timed() context manager — wraps check_availability and book_appointment

**Status:** Complete
**Notes:** Run sql/indexes.sql once in Supabase SQL Editor.

---

### Task 6: Graceful Degradation ✅
- [x] 6.1 ServiceMode enum — FULL / DEGRADED / EMERGENCY in service_mode.py
- [x] 6.2 Health checks — check_database (Supabase ping), check_calendar (creds.valid)
- [x] 6.3 determine_mode() — called at entrypoint, sets mode before session starts
- [x] 6.4 Localized notices — mode_notice() in en/ms/ta/zh for DEGRADED and EMERGENCY

**Status:** Complete

---

## Week 3: Medium Priority (NICE TO HAVE) 💡

### Task 7: State Management ✅
- [x] 7.1 Add state persistence to database — save_conversation_state, load_conversation_state, clear_conversation_state in database.py; conversation_states table in sql/indexes.sql
- [x] 7.2 State tracking in agent — _conv_state dict saved after every turn in on_user_turn_completed; cleared on successful booking, cancellation, and transfer
- [x] 7.3 Resume capability — entrypoint loads existing state on connect; if found, plays localised resume message instead of greeting; restores _detected_lang and system prompt
- [x] 7.4 Cleanup — state cleared in _on_disconnect handler

**Status:** Complete

---

### Task 8: Enhanced Prompts ✅
- [x] 8.1 _build_prompt() — injects today_date, tomorrow_date, current_day, tomorrow_day, current_time, business_hours, business_phone
- [x] 8.2 Date injection — LLM instructed to always use YYYY-MM-DD; never pass "tomorrow"/day names to tools
- [x] 8.3 Language-specific behaviours — Malay (Encik/Puan, jap eh, okay boleh), Tamil (அய்யா/அம்மா, Malaysian Tamil phrases), Mandarin (您, 稍等啊), English (natural Malaysian English)
- [x] 8.4 PROHIBITED section — no invented availability, no booking without full confirmation, no day names to tools
- [x] 8.5 Name confirmation — step-by-step rules (ask → spell → read back → confirm) in all 4 prompts

**Status:** Complete

---

### Task 9: Production Deployment
- [ ] 9.1 Update Dockerfile (multi-stage)
- [ ] 9.2 Create .dockerignore
- [ ] 9.3 Add health endpoint
- [ ] 9.4 Add graceful shutdown
- [ ] 9.5 Build and test Docker image

**Status:** Not started

---

### Task 10: Documentation
- [x] 10.1 Update INSTRUCTION.md — full rewrite documenting actual stack, multilingual flow, known fixes applied
- [ ] 10.2 Create README.md
- [ ] 10.3 Create RUNBOOK.md
- [ ] 10.4 Review all documentation

**Status:** Partially complete (INSTRUCTION.md done)

---

## Summary

**Total Progress:** 8/10 tasks (80%)

**Critical tasks completed:** 3/3 ✅ (Tasks 1-3)
**High priority completed:** 3/3 ✅ (Tasks 4-6)
**Medium priority completed:** 2/4 (Tasks 7-8 done, 9-10 pending)

---

## Launch Readiness

### Critical (MUST HAVE) ✅
- [x] Fallback adapters working — STT, LLM, TTS all have fallbacks
- [x] 47 tests passing
- [x] Structured logging + PII filtering enabled

### High Priority (SHOULD HAVE) ✅
- [x] Input validation + rate limiting working
- [x] Database indexes optimised
- [x] Graceful degradation — FULL/DEGRADED/EMERGENCY modes

### Ready to Launch? ✅ YES (for staging)
**Remaining:** Docker packaging (Task 9) and full docs (Task 10) before production.

---

## Notes & Learnings

- ElevenLabs Scribe STT: correct param is `use_realtime=True`, not `model="scribe_v2_realtime"`
- ElevenLabs TTS: `language` param is valid for eleven_multilingual_v2
- Groq Whisper `language="en"` was the root cause of Malay/Tamil/Mandarin not working — locked transcription to English
- Windows: `pip install tzdata` required for Asia/Kuala_Lumpur timezone
- conftest.py is auto-loaded by pytest, cannot be imported directly in test files
- lang_handler returns None for ambiguous/short text — callers should use `or self._detected_lang`

---

**Last updated:** 2026-05-22
**Updated by:** Claude Code
