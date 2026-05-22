"""
Maya – Malaysian Multilingual Voice Receptionist
─────────────────────────────────────────────────
STT : ElevenLabs Scribe v2 Realtime (primary) → Deepgram Nova-3 → Groq Whisper
TTS : ElevenLabs eleven_multilingual_v2 per language (primary) → Edge TTS (fallback)
LLM : Groq llama-3.3-70b-versatile (primary) → Groq llama-3.1-8b-instant (fallback)
VAD : Silero
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Annotated, AsyncIterable, Optional

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    ModelSettings,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    llm as llm_module,
    stt as stt_module,
    tokenize,
    tts as tts_module,
    utils,
)
from livekit.plugins import deepgram, elevenlabs, silero
from livekit.plugins import openai as lk_openai

from booking_manager import BookingManager
from config import Config
from database import BookingDatabase
from language_handler import LanguageHandler
from observability import (
    setup_logging, log_session_start, log_session_end,
    log_language_switch, log_transfer, log_fallback, timed,
)
from service_mode import ServiceMode, determine_mode, mode_notice
from tts_edge import EdgeTTS

load_dotenv()
setup_logging()
logger = logging.getLogger(__name__)

config = Config()
lang_handler = LanguageHandler()

# ---------------------------------------------------------------------------
# ElevenLabs voice IDs — eleven_multilingual_v2, one voice per language
# ---------------------------------------------------------------------------

ELEVENLABS_VOICES = {
    "en": "kdmDKE6EkgrWrrykO9Qt",
    "ms": "qAJVXEQ6QgjOQ25KuoU8",
    "zh": "tOuLUAIdXShmWH7PEUrU",
    "ta": "mGboHvCVOXWYeFL8KTR0",
}

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS = {
    "en": """\
You are Maya, the voice receptionist for {business_name}.
Hours: {business_hours} MYT. Today is {current_date} ({current_day}). Tomorrow is {tomorrow_date} ({tomorrow_day}).

════ VOICE RULES ════
1. Phone call — maximum 2 sentences per response.
2. ONE question per turn — never ask two things at once.
3. No bullet points, lists, or markdown — spoken words only.
4. Natural Malaysian English: "Sure, no problem.", "Let me check for you ah.", "Can, can."

════ DATE RULES ════
- ALWAYS convert to YYYY-MM-DD before calling any tool.
- "tomorrow" = {tomorrow_date}, "today" = {today_date}
- Count forward from today ({current_day}, {today_date}) to resolve any day name.
- Never pass day names or "tomorrow" to tools — only YYYY-MM-DD.

════ NAME RULES ════
Step 1 — Ask: "May I have your full name please?"
Step 2 — If not 100% sure of spelling, next turn ask: "Could you spell that for me?"
Step 3 — Read back letter by letter: "So that's R-A-J-E-S-H, Rajesh — is that right?"
Step 4 — Wait for confirmation before moving on.
Malaysian names: Malay (Ahmad bin Zainal), Chinese (Tan Wei Ming), Indian (Priya a/p Krishnan).

════ BOOKING FLOW — one step per turn ════
Turn 1: Want appointment → ask preferred date
Turn 2: check_availability(YYYY-MM-DD) → offer 2 slots
Turn 3: Confirm chosen time
Turn 4: Ask service/reason
Turn 5: Ask full name (Step 1)
Turn 6: Spelling if unclear (Step 2)
Turn 7: Ask phone number
Turn 8: Read back all details for confirmation
Turn 9: book_appointment

════ OTHER TOOLS ════
cancel_appointment, reschedule_appointment, answer_faq, transfer_to_human.
transfer_to_human: use if caller is upset, medical emergency, billing, or outside your scope.

════ PROHIBITED ════
- Never invent availability — always call check_availability first.
- Never book without full name, phone, date, time, service confirmed.
- Never make up clinic details — use answer_faq for clinic questions.
- Never pass "tomorrow" / day names to tools.

LANGUAGE: If caller speaks Malay, Tamil, or Mandarin — switch immediately.""",

    "ms": """\
Awak Maya, resepsionis suara {business_name}.
Waktu: {business_hours} WMT. Hari ini {current_date} ({current_day}), pukul {current_time}.

PERATURAN SUARA:
- Maksimum 2 ayat. Satu soalan setiap giliran.
- Bahasa semula jadi: "Okay, boleh.", "Jap eh.", "Saya semak dulu.", "Tak apa."
- Alamat formal: Encik / Puan (tanya jantina kalau tak pasti).

PERATURAN TARIKH:
- Tukar ke YYYY-MM-DD sebelum guna alat.
- "esok" = {tomorrow_date} ({tomorrow_day}), "hari ini" = {today_date}
- Jangan hantar nama hari ke alat.

PENGENDALIAN NAMA:
- Tanya ejaan kalau tak pasti: "Boleh ejakan nama tu?"
- Baca semula: "Jadi A-H-M-A-D — betul?"

LANGKAH TEMPAHAN (satu langkah setiap giliran):
1. Tanya tarikh → 2. Semak slot → 3. Pilih masa → 4. Jenis perkhidmatan
5. Nama → 6. Ejaan jika perlu → 7. Nombor telefon
8. Baca semula semua → 9. Buat tempahan

DILARANG: Jangan reka maklumat. Jangan tempah tanpa sahkan semua butiran.
ALAT: check_availability, book_appointment, cancel_appointment, reschedule_appointment, answer_faq, transfer_to_human.""",

    "ta": """\
நீங்கள் {business_name}-இன் வரவேற்பாளர் Maya.
நேரம்: {business_hours} MYT. இன்று {current_date} ({current_day}), இப்போது {current_time}.

குரல் விதிகள்:
- அதிகபட்சம் 2 வாக்கியங்கள். ஒரு நேரத்தில் ஒரே கேள்வி.
- மரியாதையான முகவரி: அய்யா / அம்மா.
- இயற்கையான மலேசிய தமிழ்: "சரி, பார்க்கிறேன்.", "ஒரு நிமிஷம்.", "முடியும்."

தேதி விதிகள்:
- YYYY-MM-DD வடிவத்தில் மாற்றவும்.
- "நாளை" = {tomorrow_date}, "இன்று" = {today_date}
- நாள் பெயர்களை கருவிகளுக்கு அனுப்பாதீர்கள்.

பெயர் விதிகள்:
- "பெயரை spelling சொல்லுங்களேன்?"
- "V-I-J-A-Y — சரியா?"

முன்பதிவு படிகள் (ஒரு படி மட்டும்):
1. தேதி → 2. இடங்கள் சரிபார் → 3. நேரம் → 4. சேவை
5. பெயர் → 6. Spelling → 7. தொலைபேசி
8. விவரங்கள் உறுதிப்படுத்துங்கள் → 9. முன்பதிவு

தடைசெய்யப்பட்டவை: தகவல்களை கண்டுபிடிக்காதீர்கள். முழு விவரம் இல்லாமல் முன்பதிவு வேண்டாம்.
கருவிகள்: check_availability, book_appointment, cancel_appointment, reschedule_appointment, answer_faq, transfer_to_human.""",

    "zh": """\
你是{business_name}的语音接待员Maya。
营业时间：{business_hours} 马来西亚时间。今天{current_date}（{current_day}），现在{current_time}。

语音规则：
- 最多2句话。每次只问一个问题。
- 使用敬语「您」。自然华语：「好的，没问题。」「我查一下哦。」「稍等啊。」

日期规则：
- 转成YYYY-MM-DD再调用工具。
- "明天" = {tomorrow_date}，"今天" = {today_date}
- 不要传日期名称给工具。

姓名规则：
- 「请问您怎么称呼？」→ 如不确定，「可以拼一下名字吗？」
- 「所以是T-A-N伟明——对吗？」

预约流程（每轮一步）：
1. 询问日期 → 2. 查询时段 → 3. 确认时间 → 4. 服务类型
5. 全名 → 6. 拼写确认 → 7. 电话号码
8. 复述全部信息 → 9. 完成预约

禁止：不得编造信息。未确认全部信息前不得预约。
工具：check_availability、book_appointment、cancel_appointment、reschedule_appointment、answer_faq、transfer_to_human。""",
}


def _build_prompt(language: str) -> str:
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    template = SYSTEM_PROMPTS.get(language, SYSTEM_PROMPTS["en"])
    return template.format(
        business_name=config.business_name,
        current_date=now.strftime("%d %B %Y"),
        current_day=now.strftime("%A"),
        today_date=now.strftime("%Y-%m-%d"),
        tomorrow_date=tomorrow.strftime("%Y-%m-%d"),
        tomorrow_day=tomorrow.strftime("%A"),
        current_time=now.strftime("%H:%M"),
        business_hours=f"{config.business_hours_start}–{config.business_hours_end}",
        business_phone=config.business_phone or "our front desk",
    )


LANGUAGE_PROBE = (
    f"Hello, thank you for calling {config.business_name}! "
    "I'm Maya. I can assist you in English, Bahasa Melayu, Tamil, or Mandarin — "
    "just speak in whichever you prefer. How may I help you today?"
)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class MayaAgent(Agent):
    def __init__(self, *, tts_engines: dict, tts_fallbacks: dict,
                 db: Optional["BookingDatabase"] = None, room_id: str = ""):
        self._detected_lang: str = "en"
        self._tts_engines = tts_engines
        self._tts_fallbacks = tts_fallbacks
        self.bm = BookingManager()
        self._db = db
        self._room_id = room_id
        # Tracks in-progress booking info for state persistence
        self._conv_state: dict = {"step": 0, "lang": "en", "collected": {}}
        super().__init__(instructions=_build_prompt("en"))

    # ------------------------------------------------------------------
    # TTS: try ElevenLabs first, fall back to EdgeTTS on any error
    # ------------------------------------------------------------------

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ):
        # Collect full text so we can retry with fallback if primary fails
        text_chunks: list[str] = []
        async for chunk in text:
            text_chunks.append(chunk)

        lang = self._detected_lang
        primary = self._tts_engines.get(lang, self._tts_engines["en"])
        fallback = self._tts_fallbacks.get(lang, self._tts_fallbacks["en"])

        activity = self._get_activity_or_raise()
        conn_options = activity.session.conn_options.tts_conn_options

        for attempt, tts_to_use in enumerate((primary, fallback)):
            adapted = tts_to_use
            if not adapted.capabilities.streaming:
                adapted = tts_module.StreamAdapter(
                    tts=adapted,
                    sentence_tokenizer=tokenize.blingfire.SentenceTokenizer(
                        retain_format=True
                    ),
                )
            try:
                async with adapted.stream(conn_options=conn_options) as stream:
                    for chunk in text_chunks:
                        stream.push_text(chunk)
                    stream.end_input()
                    async for ev in stream:
                        yield ev.frame
                return  # success
            except Exception as exc:
                if attempt == 0:
                    log_fallback("tts", type(primary).__name__, type(fallback).__name__, str(exc))
                else:
                    logger.error("Fallback TTS also failed for lang=%s: %s", lang, exc)
                    raise

    # ------------------------------------------------------------------
    # Language detection
    # ------------------------------------------------------------------

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        try:
            text = (new_message.text_content or "").strip()
            logger.info("User said: %r | lang=%s", text[:80], self._detected_lang)

            words = text.split()
            if len(words) <= 1 and len(text) < 6:
                logger.warning("Ignoring likely echo/noise: %r", text)
                new_message.content = []
                return

            detected = await self._detect_language(text)
            if detected != self._detected_lang:
                log_language_switch(self._detected_lang, detected)
                self._detected_lang = detected
                self.update_instructions(_build_prompt(detected))

            # Persist conversation state after every turn
            self._conv_state["lang"] = self._detected_lang
            if self._db and self._room_id:
                await self._db.save_conversation_state(self._room_id, self._conv_state)

        except Exception:
            logger.exception("Language detection hook error")

        await super().on_user_turn_completed(turn_ctx, new_message)

    async def _detect_language(self, text: str) -> str:
        if not text:
            return self._detected_lang
        return lang_handler.detect_language(text) or self._detected_lang

    # ------------------------------------------------------------------
    # Function tools
    # ------------------------------------------------------------------

    @function_tool
    async def check_availability(
        self,
        date: Annotated[str, "Date in YYYY-MM-DD format"],
    ) -> str:
        """Check which appointment slots are open on a given date."""
        with timed("check_availability"):
            return await self.bm.get_slots(date)

    @function_tool
    async def book_appointment(
        self,
        name: Annotated[str, "Customer full name — confirmed spelling"],
        phone: Annotated[str, "Phone number with country code e.g. +601X-XXXXXXX"],
        date: Annotated[str, "Appointment date YYYY-MM-DD"],
        time: Annotated[str, "Appointment time HH:MM (24-hour)"],
        service: Annotated[str, "Service type e.g. General Consultation"],
    ) -> str:
        """Book a new appointment. Confirm all details with customer first."""
        with timed("book_appointment"):
            result = await self.bm.book(
                phone=phone, name=name, date=date, time=time,
                service=service, language=self._detected_lang,
            )
        if "Confirmed" in result and self._db and self._room_id:
            await self._db.clear_conversation_state(self._room_id)
            self._conv_state = {"step": 0, "lang": self._detected_lang, "collected": {}}
        return result

    @function_tool
    async def cancel_appointment(
        self,
        phone: Annotated[str, "Customer phone number"],
        name: Annotated[str, "Customer name (optional)"] = None,
    ) -> str:
        """Cancel the customer's most recent active appointment."""
        result = await self.bm.cancel(phone=phone, name=name)
        if "cancelled" in result and self._db and self._room_id:
            await self._db.clear_conversation_state(self._room_id)
            self._conv_state = {"step": 0, "lang": self._detected_lang, "collected": {}}
        return result

    @function_tool
    async def reschedule_appointment(
        self,
        phone: Annotated[str, "Customer phone number"],
        new_date: Annotated[str, "New date YYYY-MM-DD"],
        new_time: Annotated[str, "New time HH:MM (24-hour)"],
        name: Annotated[str, "Customer name (optional)"] = None,
    ) -> str:
        """Move the customer's existing appointment to a new slot."""
        return await self.bm.reschedule(
            phone=phone, new_date=new_date, new_time=new_time, name=name,
        )

    @function_tool
    async def answer_faq(
        self,
        question: Annotated[str, "Customer question about hours, location, payment, etc."],
    ) -> str:
        """Answer frequently asked questions about the clinic."""
        return await self.bm.get_faq_answer(question)

    @function_tool
    async def transfer_to_human(
        self,
        reason: Annotated[str, "Why a human staff member is needed"],
    ) -> str:
        """Transfer the call to human staff."""
        log_transfer(reason)
        if self._db and self._room_id:
            await self._db.clear_conversation_state(self._room_id)
        responses = {
            "en": "Of course — please hold while I connect you to our staff.",
            "ms": "Baik, sila tunggu — saya sambungkan anda ke petugas kami.",
            "ta": "நிச்சயமாக — காத்திருங்கள், ஊழியரிடம் இணைக்கிறேன்.",
            "zh": "好的，请稍候——为您转接工作人员。",
        }
        return responses.get(self._detected_lang, responses["en"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    db = BookingDatabase()
    room_name = ctx.room.name if ctx.room else "unknown"
    # ── Health check → determine service mode ─────────────────────────────
    bm_temp = BookingManager()
    mode = await determine_mode(db, bm_temp._gcal)
    logger.info("Service mode: %s", mode.value)

    session_record = await db.create_voice_session(livekit_room_id=room_name)
    session_db_id = session_record["id"] if session_record else None
    session_start = __import__("time").monotonic()
    log_session_start(room_id=room_name, job_id=str(ctx.job.id) if ctx.job else "-")

    # ── STT: ElevenLabs Scribe → Deepgram Nova-3 → Groq Whisper ──────────
    stt_engine = stt_module.FallbackAdapter(
        [
            elevenlabs.STT(api_key=config.elevenlabs_api_key, use_realtime=True),
            deepgram.STT(api_key=config.deepgram_api_key, model="nova-3"),
            lk_openai.STT(
                model="whisper-large-v3-turbo",
                api_key=config.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            ),
        ]
    )

    # ── LLM: Groq llama-3.3-70b → Groq llama-3.1-8b-instant ─────────────
    llm_engine = llm_module.FallbackAdapter(
        [
            lk_openai.LLM(
                model="llama-3.3-70b-versatile",
                api_key=config.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            ),
            lk_openai.LLM(
                model="llama-3.1-8b-instant",
                api_key=config.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            ),
        ]
    )

    # ── TTS primary: ElevenLabs eleven_multilingual_v2 per language ───────
    tts_engines = {
        lang: elevenlabs.TTS(
            voice_id=voice_id,
            model="eleven_multilingual_v2",
            api_key=config.elevenlabs_api_key,
            language=lang,
        )
        for lang, voice_id in ELEVENLABS_VOICES.items()
    }

    # ── TTS fallback: Edge TTS per language ───────────────────────────────
    tts_fallbacks = {lang: EdgeTTS(language=lang) for lang in ELEVENLABS_VOICES}

    session = AgentSession(
        stt=stt_engine,
        llm=llm_engine,
        tts=tts_engines["en"],
        vad=silero.VAD.load(
            activation_threshold=0.6,
            min_speech_duration=0.15,
            min_silence_duration=0.6,
        ),
        min_interruption_duration=0.5,
        min_interruption_words=2,
        false_interruption_timeout=2.0,
        min_endpointing_delay=0.6,
    )

    # ── Resume detection ──────────────────────────────────────────────────
    existing_state = await db.load_conversation_state(room_name)
    resume_lang = existing_state.get("lang", "en") if existing_state else "en"
    resume_notice: Optional[str] = None
    if existing_state:
        resume_notice = {
            "en": "I see we were in the middle of scheduling — let me pick up where we left off.",
            "ms": "Nampaknya kita terganggu tadi — saya sambung semula ya.",
            "ta": "நாம் அமர்வுக்கு நடுவில் இருந்தோம் — தொடர்கிறேன்.",
            "zh": "看来我们之前被中断了——我继续为您服务。",
        }.get(resume_lang, "I see we were in the middle of scheduling — let me pick up where we left off.")

    agent = MayaAgent(tts_engines=tts_engines, tts_fallbacks=tts_fallbacks,
                      db=db, room_id=room_name)
    if existing_state:
        agent._conv_state = existing_state
        agent._detected_lang = resume_lang
        agent.update_instructions(_build_prompt(resume_lang))

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(),
    )

    # In EMERGENCY mode, skip booking flow and immediately transfer
    if mode == ServiceMode.EMERGENCY:
        notice = mode_notice(mode, "en")
        await session.say(notice)
    else:
        if mode == ServiceMode.DEGRADED:
            notice = mode_notice(mode, "en")
            await session.say(notice)
        if resume_notice:
            await session.say(resume_notice)
        else:
            await session.say(LANGUAGE_PROBE)

    logger.info(
        "Maya started | room=%s | STT=ElevenLabs→Deepgram→Groq | TTS=ElevenLabs→EdgeTTS",
        room_name,
    )

    @ctx.room.on("disconnected")
    def _on_disconnect(*_):
        duration = __import__("time").monotonic() - session_start
        log_session_end(room_id=room_name, duration_sec=duration)
        asyncio.create_task(db.end_voice_session(session_db_id or ""))
        asyncio.create_task(db.clear_conversation_state(room_name))


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
