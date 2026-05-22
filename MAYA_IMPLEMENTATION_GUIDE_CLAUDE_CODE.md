# Maya Production Implementation Guide for Claude Code

This guide is optimized for use with Claude Code in VS Code. Each task can be executed step-by-step with Claude's help.

---

## 🚀 Quick Start with Claude Code

### How to use this guide:

1. Open this file in VS Code
2. Open Claude Code (Cmd/Ctrl + Shift + P → "Claude Code: Open")
3. Select a task below and ask Claude Code to implement it
4. Claude Code will read the instructions, create/modify files, and test the changes

### Example prompts for Claude Code:

```
"Implement task 1.1 - add fallback adapters for STT/LLM/TTS"
"Create the pytest test suite from task 2.1"
"Add OpenTelemetry tracing as described in task 3.1"
"Help me implement error handling from the critical issues section"
```

---

## 📋 Implementation Checklist

Copy this to a separate file `PROGRESS.md` to track your progress:

```markdown
# Maya Implementation Progress

## Week 1: Critical Issues ⏰
- [ ] 1.1 Fallback Adapters
- [ ] 1.2 Error Recovery
- [ ] 2.1 Testing Framework
- [ ] 2.2 Test Suite
- [ ] 3.1 OpenTelemetry Setup
- [ ] 3.2 Structured Logging
- [ ] 3.3 Metrics Collection

## Week 2: High Priority
- [ ] 4.1 Secrets Management
- [ ] 4.2 Input Validation
- [ ] 4.3 Rate Limiting
- [ ] 4.4 PII Filtering
- [ ] 5.1 Connection Pooling
- [ ] 5.2 Query Optimization
- [ ] 5.3 Caching Layer
- [ ] 6.1 Service Modes
- [ ] 6.2 Health Checks

## Week 3: Medium Priority
- [ ] 7.1 State Management
- [ ] 8.1 Prompt Improvements
- [ ] 9.1 Deployment Updates
- [ ] 10.1 Documentation

Status: 0/25 tasks completed (0%)
Last updated: [DATE]
```

---

## 🎯 TASK 1: Fallback Adapters (CRITICAL)

**File:** `agent.py`
**Estimated time:** 2 hours
**Dependencies:** None

### What to tell Claude Code:

```
I need to add FallbackAdapter for STT, LLM, and TTS to prevent single points of failure.

Requirements:
1. STT fallback chain: ElevenLabs Scribe → Deepgram Nova-3 → Groq Whisper
2. LLM fallback chain: Groq Llama → OpenAI GPT-4o-mini → Anthropic Claude
3. TTS fallback: ElevenLabs → Cartesia for each language
4. Add try-except in session handler with graceful error recovery
5. Log all fallback activations

Current setup uses:
- elevenlabs.STT(model="scribe-v2")
- groq.LLM(model="llama-3.3-70b-versatile")
- elevenlabs.TTS() per language

Please implement FallbackAdapter wrappers and update MayaAgent class.
```

### Files that will be modified:
- `agent.py` - Add FallbackAdapter imports and update MayaAgent.__init__
- `config.py` - Add new API key environment variables
- `.env.example` - Document new required keys

### Validation:
```bash
# After Claude Code implements, test with:
python agent.py console

# Manually disable ElevenLabs key to test fallback:
ELEVENLABS_API_KEY="invalid" python agent.py console
# Should fall back to Deepgram automatically
```

### Success criteria:
- [ ] Agent starts without errors
- [ ] Fallback activates when primary fails
- [ ] Logs show "Falling back to..." messages
- [ ] No crashes when provider is down

---

## 🎯 TASK 2: Testing Framework (CRITICAL)

**Files:** `tests/test_maya_booking.py`, `tests/conftest.py`
**Estimated time:** 3 hours
**Dependencies:** None

### What to tell Claude Code:

```
Create a pytest test suite for Maya's booking flow.

Requirements:
1. Test complete English booking (9 turns)
2. Test Malay booking (language detection + booking)
3. Test name spelling confirmation flow
4. Test no availability scenario
5. Test emergency transfer
6. Add pytest configuration in conftest.py
7. Add pytest and pytest-asyncio to requirements.txt

The booking flow is:
1. User requests appointment → ask date
2. Agent checks availability → offers slots
3. User picks slot → ask service
4. Agent asks name
5. If unclear, ask spelling → read back letters
6. Agent asks phone
7. Agent reads back all details → ask confirm
8. User confirms → book appointment

Current function tools:
- check_availability(date: YYYY-MM-DD)
- book_appointment(name, phone, date, time, service)
- transfer_to_human(reason)

Please create comprehensive tests using livekit.agents.test framework.
```

### Files that will be created:
- `tests/test_maya_booking.py` - Main test suite
- `tests/test_maya_languages.py` - Language-specific tests
- `tests/conftest.py` - Pytest configuration
- `tests/__init__.py` - Package marker

### Validation:
```bash
# After Claude Code implements:
pip install pytest pytest-asyncio
pytest tests/ -v

# Expected output:
# tests/test_maya_booking.py::test_english_booking_happy_path PASSED
# tests/test_maya_booking.py::test_malay_booking PASSED
# ... etc
```

### Success criteria:
- [ ] At least 5 tests pass
- [ ] Tests cover English and Malay flows
- [ ] Name spelling test validates confirmation
- [ ] Tests run in under 2 minutes
- [ ] CI/CD ready (no hardcoded values)

---

## 🎯 TASK 3: OpenTelemetry & Logging (CRITICAL)

**File:** `agent.py`, new file `observability.py`
**Estimated time:** 2 hours
**Dependencies:** Task 1 (optional but recommended)

### What to tell Claude Code:

```
Add OpenTelemetry tracing and structured logging to Maya.

Requirements:
1. Set up OpenTelemetry tracer with OTLP exporter
2. Add tracing spans for: session start, booking flow, tool calls
3. Set up structured logging with room_id and job_id context
4. Add metrics: booking_counter, booking_latency, session_success_rate
5. Log all errors with stack traces
6. Export traces to LiveKit Cloud or console in dev mode

Current session handler:
@server.rtc_session(agent_name="maya-receptionist")
async def receptionist_session(ctx: JobContext):
    # ... session setup

Please add:
- OpenTelemetry setup in observability.py
- Tracing decorators for all async functions
- Structured logging with contextual fields
- Metrics collection for key operations
```

### Files to create/modify:
- `observability.py` - New file with OpenTelemetry setup
- `agent.py` - Import and use tracing
- `booking_manager.py` - Add tracing to booking functions
- `requirements.txt` - Add opentelemetry packages

### Validation:
```bash
# After implementation:
python agent.py dev

# Check logs show structured format:
# 2026-05-21 14:30:15 - maya - INFO - [room=abc123] - Starting session
# 2026-05-21 14:30:16 - maya - INFO - [room=abc123] - Booking attempt

# Check traces (if using LiveKit Cloud):
# Visit https://cloud.livekit.io → Observability → Traces
```

### Success criteria:
- [ ] Logs include room_id and job_id
- [ ] Traces show in console or LiveKit Cloud
- [ ] Errors include full stack traces
- [ ] Metrics increment on bookings
- [ ] No performance impact (<50ms overhead)

---

## 🎯 TASK 4: Security Hardening (HIGH PRIORITY)

**Files:** Multiple
**Estimated time:** 3 hours
**Dependencies:** None

### What to tell Claude Code:

```
Add security improvements to Maya:

1. Input Validation (booking_manager.py):
   - Validate phone numbers (Malaysian format: 01X-XXXX-XXXX)
   - Validate dates (must be future, max 90 days ahead)
   - Sanitize names (remove special chars, max 100 chars)
   - Validate all inputs before database operations

2. Rate Limiting (agent.py):
   - Max 3 booking attempts per phone per hour
   - Track by phone number
   - Return friendly error message when exceeded

3. PII Filtering (agent.py):
   - Create logging filter to scrub phone numbers
   - Replace with [PHONE] placeholder
   - Also scrub emails and NRIC numbers

4. Environment (config.py):
   - Add ENV variable (dev/staging/production)
   - Add comments about secrets manager for production
   - Never log API keys

Current files:
- booking_manager.py has book_appointment() function
- agent.py has logging setup
- config.py loads environment variables

Please implement all security measures with proper error messages.
```

### Files to modify:
- `booking_manager.py` - Add validation functions
- `agent.py` - Add rate limiter and PII filter
- `config.py` - Add ENV variable and security comments
- `.env.example` - Add ENV=development

### Validation:
```bash
# Test input validation:
python -c "
from booking_manager import validate_phone_number
assert validate_phone_number('0123456789')
assert not validate_phone_number('123')
print('✓ Phone validation works')
"

# Test rate limiting:
# Make 4 booking attempts with same phone in agent
# 4th attempt should be rejected

# Test PII filtering:
# Check logs don't contain real phone numbers
grep -r "012345" maya.log  # Should find [PHONE] not real numbers
```

### Success criteria:
- [ ] Invalid phone numbers rejected with helpful message
- [ ] Past dates rejected
- [ ] Names sanitized (no SQL injection possible)
- [ ] Rate limiter blocks after 3 attempts/hour
- [ ] Logs show [PHONE] instead of real numbers
- [ ] No API keys in logs or output

---

## 🎯 TASK 5: Performance Optimization (HIGH PRIORITY)

**Files:** `database.py`, `booking_manager.py`
**Estimated time:** 2 hours
**Dependencies:** None

### What to tell Claude Code:

```
Optimize Maya's performance:

1. Connection Pooling (database.py):
   - Add Supabase client options with pool_size=10
   - Enable auto_refresh_token and persist_session

2. Query Optimization (database.py):
   - Change SELECT * to select specific columns
   - Add .limit() to all queries
   - Create SQL for database indexes

3. Caching (booking_manager.py):
   - Cache FAQ responses for 1 hour (using dict with expiry)
   - Cache business config (using @lru_cache)
   - Clear cache on updates

4. Batch Operations (database.py):
   - Replace loops with single batch updates
   - Use .in_() for multi-record queries

Current setup:
- Supabase client created simply: create_client(url, key)
- Queries use .select("*")
- No caching implemented
- Individual updates in loops

Please optimize without changing external API.
```

### Files to modify:
- `database.py` - Add pooling, optimize queries
- `booking_manager.py` - Add caching
- `sql/indexes.sql` - New file with CREATE INDEX statements

### Validation:
```bash
# After implementation, test query speed:
python -c "
import time
from database import get_bookings

start = time.time()
bookings = get_bookings(contact_id='test-id')
duration = time.time() - start

print(f'Query took {duration*1000:.0f}ms')
assert duration < 0.1, 'Query too slow!'
print('✓ Performance acceptable')
"

# Apply database indexes:
# Copy sql/indexes.sql content to Supabase SQL editor and run
```

### Success criteria:
- [ ] Database queries <100ms P95
- [ ] FAQ responses instant (from cache)
- [ ] Indexes created on bookings and availability tables
- [ ] No N+1 query problems
- [ ] Cache invalidation works correctly

---

## 🎯 TASK 6: Graceful Degradation (HIGH PRIORITY)

**File:** `agent.py`
**Estimated time:** 2 hours
**Dependencies:** Task 3 (for logging)

### What to tell Claude Code:

```
Add graceful degradation to Maya:

1. Service Modes (agent.py):
   - Create ServiceMode enum: FULL, DEGRADED, EMERGENCY
   - FULL: All features working
   - DEGRADED: Database works, calendar down → store bookings without sync
   - EMERGENCY: Database down → transfer all calls to human

2. Health Checks (agent.py):
   - Check database connection (SELECT 1)
   - Check calendar connection (if configured)
   - Determine service mode based on what's available
   - Run health check before each session

3. Prompt Updates (agent.py):
   - Modify system prompt based on service mode
   - In DEGRADED: Inform user calendar sync delayed
   - In EMERGENCY: Only offer human transfer

4. Monitoring (agent.py):
   - Log service mode changes
   - Add metric for mode transitions
   - Alert when leaving FULL mode

Current MayaAgent class has _build_prompt(lang) method.
receptionist_session() creates agent and starts session.

Please implement service mode system with health checks.
```

### Files to modify:
- `agent.py` - Add ServiceMode, health checks, prompt modifications
- `database.py` - Add health check method
- `google_calendar.py` - Add health check method (if exists)

### Validation:
```bash
# Test FULL mode (all services up):
python agent.py console
# Should work normally

# Test DEGRADED mode (stop calendar):
# Temporarily break google_token.json
mv google_token.json google_token.json.bak
python agent.py console
# Should still book but warn about calendar

# Test EMERGENCY mode (stop database):
# Use invalid Supabase URL
SUPABASE_URL="https://invalid.supabase.co" python agent.py console
# Should only offer human transfer
```

### Success criteria:
- [ ] Agent works in all 3 modes
- [ ] Mode transitions logged clearly
- [ ] Users informed about degraded service
- [ ] EMERGENCY mode only offers transfer
- [ ] Health checks run before each session
- [ ] No crashes when services down

---

## 🎯 TASK 7: Conversation State Management (MEDIUM)

**Files:** `database.py`, `agent.py`
**Estimated time:** 2 hours
**Dependencies:** Task 5 (database optimization)

### What to tell Claude Code:

```
Add conversation state persistence:

1. Database Schema (database.py):
   - Add save_conversation_state(room_id, state_dict)
   - Add load_conversation_state(room_id)
   - State includes: booking_in_progress, collected_info, current_step

2. State Tracking (agent.py):
   - Initialize self.conversation_state in MayaAgent
   - Update state after each user turn
   - Save to database after updates
   - Load state on session start (for reconnections)

3. Resume Capability (agent.py):
   - Check for existing state on session start
   - If found, resume from last step
   - Example: "I see we were scheduling an appointment. You were about to give me your phone number."

Current setup:
- No state persistence
- Each session starts fresh
- User must restart booking if disconnected

Please implement state management with resume capability.
```

### Files to modify:
- `database.py` - Add state save/load functions
- `agent.py` - Track and persist state
- Supabase: Add `conversation_states` table

### Validation:
```bash
# Test state persistence:
# 1. Start booking flow
# 2. Get to step 5 (name collection)
# 3. Close connection (Ctrl+C)
# 4. Restart with same room_id
# 5. Should resume from step 5

# Manual test in console mode:
python agent.py console
# Say: "I want an appointment"
# Say: "Tomorrow at 2pm"
# Ctrl+C to disconnect
python agent.py console
# Should say: "I see we were scheduling..."
```

### Success criteria:
- [ ] State saves after each turn
- [ ] State loads on reconnection
- [ ] Agent resumes from correct step
- [ ] Handles missing state gracefully
- [ ] State cleanup after completion

---

## 🎯 TASK 8: Enhanced Prompts (MEDIUM)

**File:** `agent.py`
**Estimated time:** 1 hour
**Dependencies:** None

### What to tell Claude Code:

```
Improve Maya's system prompts:

1. Enhanced Instructions (agent.py):
   - Add CRITICAL RULES section with bold warnings
   - Add CURRENT CONTEXT with today/tomorrow dates pre-calculated
   - Add detailed BOOKING FLOW with exact steps
   - Add comprehensive EDGE CASES handling
   - Add LANGUAGE HANDLING guidelines per language
   - Add TOOL USAGE instructions with examples
   - Add PROHIBITED behaviors section

2. Date Injection:
   - Calculate today and tomorrow dates
   - Format as YYYY-MM-DD
   - Inject into prompt so LLM never uses "tomorrow"
   - Add timezone awareness

3. Language-Specific Behavior:
   - Malay: Use "Encik/Puan" formal address
   - Tamil: Use respectful pronouns
   - Mandarin: Use 您 (formal you)
   - English: Professional but friendly

Current _build_prompt(lang) method returns basic prompt.
Needs expansion with specific scenarios and examples.

Please create comprehensive prompt with all improvements.
```

### Files to modify:
- `agent.py` - Expand _build_prompt() method

### Validation:
```bash
# Test improved prompts:
python agent.py console

# Test date handling:
# Say: "I want appointment tomorrow"
# Agent should use YYYY-MM-DD in tool call, not "tomorrow"

# Test edge case handling:
# Say: "I need urgent medical help"
# Should immediately transfer

# Test language-specific behavior:
# (Malay) Say: "Saya nak buat temujanji"
# Should respond with "Encik" or "Puan"
```

### Success criteria:
- [ ] Agent never passes "tomorrow" to tools
- [ ] One question per turn enforced
- [ ] Name spelling confirmation works consistently
- [ ] Edge cases handled appropriately
- [ ] Language-specific politeness works
- [ ] No "hallucinated" information

---

## 🎯 TASK 9: Production Deployment (MEDIUM)

**Files:** `Dockerfile`, `.dockerignore`, `agent.py`
**Estimated time:** 2 hours
**Dependencies:** All critical tasks (1-3)

### What to tell Claude Code:

```
Update deployment configuration for production:

1. Dockerfile (Dockerfile):
   - Multi-stage build (builder + production)
   - Install only necessary system packages
   - Copy from builder to reduce image size
   - Run as non-root user (maya)
   - Add HEALTHCHECK endpoint
   - Use CMD ["python", "agent.py", "start"]

2. Health Check (agent.py):
   - Add aiohttp web server on port 8080
   - Create /health endpoint
   - Return {"status": "healthy"}
   - Only in production mode

3. Graceful Shutdown (agent.py):
   - Handle SIGTERM and SIGINT
   - Use asyncio.Event for shutdown signal
   - Close database connections on shutdown
   - Wait for active sessions to complete

4. .dockerignore:
   - Exclude .env, .git, tests/, __pycache__
   - Exclude .env.local, google_token.json
   - Keep only necessary files in image

Current Dockerfile is basic single-stage build.
No health check or graceful shutdown implemented.

Please create production-ready deployment files.
```

### Files to create/modify:
- `Dockerfile` - Complete rewrite with multi-stage build
- `.dockerignore` - New file
- `agent.py` - Add health endpoint and shutdown handling

### Validation:
```bash
# Build and test Docker image:
docker build -t maya-receptionist .

# Check image size (should be <500MB):
docker images maya-receptionist

# Run with health check:
docker run -p 8080:8080 --env-file .env maya-receptionist

# Test health endpoint:
curl http://localhost:8080/health
# Should return: {"status": "healthy"}

# Test graceful shutdown:
docker stop maya-receptionist  # Should stop gracefully in <10s
```

### Success criteria:
- [ ] Docker image builds without errors
- [ ] Image size <500MB
- [ ] Runs as non-root user
- [ ] Health check responds
- [ ] Graceful shutdown works
- [ ] No .env or secrets in image

---

## 🎯 TASK 10: Documentation Updates (LOW)

**Files:** `INSTRUCTION.md`, `README.md`, new `RUNBOOK.md`
**Estimated time:** 1 hour
**Dependencies:** All other tasks

### What to tell Claude Code:

```
Update documentation with production improvements:

1. INSTRUCTION.md:
   - Add "Production Checklist" section
   - Add "Performance Targets" section
   - Add "Troubleshooting Guide" section
   - Update "Stack" table with fallback providers
   - Add "Monitoring" section with metrics

2. README.md:
   - Create if doesn't exist
   - Project overview
   - Quick start guide
   - Architecture diagram (ASCII art)
   - API key setup instructions
   - Testing instructions
   - Deployment instructions

3. RUNBOOK.md (new):
   - Common issues and solutions
   - How to check logs
   - How to restart services
   - Emergency procedures
   - Rollback process
   - Contact escalation

Reference the improvements document for content.

Please create comprehensive production documentation.
```

### Files to create/modify:
- `INSTRUCTION.md` - Add production sections
- `README.md` - Create comprehensive README
- `RUNBOOK.md` - New operational runbook

### Validation:
```bash
# Check documentation is complete:
grep -q "Production Checklist" INSTRUCTION.md && echo "✓ Checklist added"
grep -q "Performance Targets" INSTRUCTION.md && echo "✓ Targets added"
test -f README.md && echo "✓ README exists"
test -f RUNBOOK.md && echo "✓ Runbook exists"

# Check documentation is readable:
# Open files in VS Code and verify formatting
```

### Success criteria:
- [ ] Production checklist covers all improvements
- [ ] Troubleshooting guide has 5+ common issues
- [ ] README includes setup instructions
- [ ] Runbook covers emergency scenarios
- [ ] All code examples are accurate
- [ ] No broken links or references

---

## 🎬 Implementation Strategy

### Option 1: Sequential (Recommended)
Do tasks in order 1→10. Each builds on the previous.

**Pros:** Safe, validates each step, no conflicts
**Cons:** Takes longer (full 3 weeks)

### Option 2: Parallel (Risky)
Do multiple tasks simultaneously with Claude Code.

**Tasks that can be done in parallel:**
- Week 1: Tasks 1, 2, 3 can be done together
- Week 2: Tasks 4, 5, 6 can be done together
- Week 3: Tasks 7, 8, 9, 10 can be done together

**Pros:** Faster (2 weeks instead of 3)
**Cons:** Higher risk of conflicts, harder to debug

### Option 3: Critical Path Only
Do only tasks 1, 2, 3 (Week 1), then launch.

**Pros:** Fastest to production (1 week)
**Cons:** Less robust, missing security and performance

### Recommended: Option 1 (Sequential)

---

## 🔄 Typical Claude Code Session

### Example workflow:

1. **Open Claude Code**
   ```
   Cmd/Ctrl + Shift + P → "Claude Code: Open"
   ```

2. **Point to this file**
   ```
   @MAYA_IMPROVEMENTS_CLAUDE_CODE.md
   ```

3. **Give specific task**
   ```
   "Implement Task 1 - Fallback Adapters. Read the requirements and update agent.py, config.py, and .env.example. Make sure to handle errors gracefully."
   ```

4. **Claude Code will:**
   - Read the task requirements
   - Analyze your existing code
   - Create/modify necessary files
   - Add error handling
   - Update documentation

5. **Review and test**
   ```bash
   python agent.py console
   ```

6. **If issues, iterate**
   ```
   "The fallback isn't working when I set invalid API key. Can you debug?"
   ```

7. **Mark complete**
   ```
   Update PROGRESS.md: [x] 1.1 Fallback Adapters
   ```

8. **Move to next task**

---

## 🚨 Important Notes

### Do's:
✅ Test each task before moving to next
✅ Commit after each completed task
✅ Update PROGRESS.md regularly
✅ Ask Claude Code to explain changes
✅ Run existing tests after changes
✅ Keep backups of working code

### Don'ts:
❌ Skip critical tasks (1-3)
❌ Implement multiple tasks without testing
❌ Commit untested code
❌ Deploy without completing Week 1
❌ Ignore errors or warnings
❌ Forget to update documentation

---

## 🆘 If Something Breaks

### Recovery process:

1. **Don't panic** - You have Git

2. **Check what changed**
   ```bash
   git status
   git diff
   ```

3. **Ask Claude Code**
   ```
   "I just implemented Task X and now Y is broken. Here's the error: [paste error]. Can you help fix it?"
   ```

4. **Rollback if needed**
   ```bash
   git reset --hard HEAD~1  # Undo last commit
   ```

5. **Try again**
   - Re-read task requirements
   - Check dependencies were completed
   - Start with smaller changes

---

## 📊 Progress Tracking

After completing each task:

1. Update PROGRESS.md
2. Test thoroughly
3. Commit with message: `feat: complete Task X - [description]`
4. Document any issues in RUNBOOK.md
5. Update estimated time if significantly different

### Completion formula:
```
Progress = (Completed Tasks / Total Tasks) × 100%
         = (X / 10) × 100%
```

### Time estimates:
- Week 1 (Critical): 7-8 hours
- Week 2 (High Priority): 7-8 hours
- Week 3 (Medium Priority): 5-6 hours
- Week 4 (Documentation): 1-2 hours

**Total:** ~20-25 hours over 2-3 weeks

---

## ✅ Final Pre-Launch Checklist

Before deploying to production:

### Critical
- [ ] Task 1: Fallback adapters working
- [ ] Task 2: At least 5 tests passing
- [ ] Task 3: Logs show structured output
- [ ] Manual test: Complete booking in all 4 languages
- [ ] Manual test: Fallback activates when provider fails

### High Priority
- [ ] Task 4: Phone validation working
- [ ] Task 4: Rate limiting prevents abuse
- [ ] Task 5: Database queries <100ms
- [ ] Task 6: Degraded mode keeps service running

### Medium Priority
- [ ] Task 7: State persistence working (nice to have)
- [ ] Task 8: Prompts improved (nice to have)
- [ ] Task 9: Docker image builds
- [ ] Task 10: Documentation updated

### Production Environment
- [ ] All .env variables set in production
- [ ] Supabase database has indexes
- [ ] Health check endpoint responds
- [ ] Monitoring/alerts configured
- [ ] Backup API keys tested

### Go/No-Go Decision
**LAUNCH if:** All Critical + High Priority tasks done
**DELAY if:** Any Critical task incomplete

---

## 📞 Getting Help

### If stuck on a task:

1. **Re-read task requirements** - Often the answer is there
2. **Check existing code** - Look for similar patterns
3. **Ask Claude Code** - "Explain how to do [specific part]"
4. **Search LiveKit docs** - https://docs.livekit.io/
5. **LiveKit Discord** - https://livekit.io/discord
6. **GitHub Issues** - https://github.com/livekit/agents/issues

### Claude Code tips:

**Good prompts:**
- "Implement Task 1.1 with error handling and logging"
- "Add tests for the booking flow following Task 2 requirements"
- "Debug why fallback isn't activating - here's the error: [paste]"

**Bad prompts:**
- "Make it better" (too vague)
- "Fix everything" (too broad)
- "Do Task 1-10" (too much at once)

**Best practice:**
One task at a time, test after each, commit when working.

---

## 🎯 Success Metrics

After completing all tasks, you should see:

### Performance
- P99 latency: <5s ✓
- TTFT: <800ms ✓
- Uptime: >99% ✓

### Quality
- Test coverage: >80% ✓
- Booking completion: >85% ✓
- Transfer rate: <10% ✓

### Operations
- Mean time to recovery: <30 minutes ✓
- Deployment frequency: Daily ✓
- Rollback time: <5 minutes ✓

### Business
- Customer satisfaction: >4/5 ✓
- Support tickets: <5/week ✓
- Cost per call: <$0.50 ✓

---

## 🚀 You're Ready!

Start with Task 1 and work your way through. Claude Code will help you implement each task step by step.

**Remember:**
- Test after each task
- Commit working code
- Update PROGRESS.md
- Don't skip critical tasks

**Good luck with your production deployment!** 🎉
