"""
Maya – Malaysian Multilingual Voice Receptionist
─────────────────────────────────────────────────
STT : ElevenLabs Scribe v2 Realtime → Deepgram Nova-3 → Groq Whisper
TTS : ElevenLabs eleven_turbo_v2_5 per language → Edge TTS fallback
LLM : Groq llama-3.3-70b-versatile → Groq llama-3.1-8b-instant
VAD : Silero
"""

import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Annotated, AsyncIterable, Optional

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    ModelSettings,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    llm as llm_module,
    stt as stt_module,
    tokenize,
    tts as tts_module,
)
from livekit.plugins import deepgram, elevenlabs, noise_cancellation, silero
from livekit.plugins import groq as lk_groq
from livekit.plugins import openai as lk_openai

# MultilingualModel is intentionally NOT imported here.
# Importing it at module level registers an inference runner, which forces
# the worker to spawn a separate subprocess that loads a neural network on
# startup. On memory-constrained containers this subprocess OOMs, closing
# the IPC channel before it sends InitializeResponse (DuplexClosed crash).
# VAD-based endpointing (min/max_endpointing_delay) covers the same need.

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

# Japanese hiragana/katakana — common Whisper hallucinations during silence.
# None of our 4 target languages (en/ms/ta/zh) use these scripts.
_HALLUCINATION_RE = re.compile(r"[぀-ヿ･-ﾟ]")
_PUNCT_ONLY_RE = re.compile(r"^[\s\W]+$")

# ---------------------------------------------------------------------------
# ElevenLabs voice IDs — one voice per language
# Do NOT pass language= to TTS: some voice IDs reject specific language codes
# and ElevenLabs closes the WebSocket immediately. Auto-detection from text
# is more reliable.
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
You are Maya, the friendly voice receptionist for {business_name}.
Clinic hours: {business_hours} MYT, Monday to Saturday. Closed Sunday and public holidays.
Today: {current_date} ({current_day}). Tomorrow: {tomorrow_date} ({tomorrow_day}). Time now: {current_time} MYT.

═══ HOW YOU SPEAK ═══
• Phone call — 1 to 2 sentences MAX per response. Be warm, brief, natural.
• Malaysian English style: "Sure, no problem.", "Let me check for you.", "Okay, noted.", "Can, can.", "Sorry ah, that slot dah taken.", "No worries."
• ONE question per turn — never ask two things at once.
• No bullet points, no lists, no markdown — you are speaking, not typing.
• Speak in a calm, friendly, professional tone like a real clinic receptionist.

═══ DATE & TIME RULES ═══
• When CALLING TOOLS: always use YYYY-MM-DD format. Never pass "tomorrow", "Friday", or any word — only the exact date.
• "today" = {today_date}, "tomorrow" = {tomorrow_date}. Count forward from {current_day} to resolve any day name.
• When SPEAKING TO CALLER: say dates naturally — "Thursday the twenty-second of May" not "2025-05-22". Say times as "ten in the morning" or "two thirty in the afternoon".
• If user says "this Friday" or "next week", silently convert to YYYY-MM-DD before calling the tool.

═══ BOOKING FLOW (strict one step per turn) ═══
If caller wants to book but doesn't say a date → call check_next_available first, then offer up to 2 dates.
If caller names a date → call check_availability for that date, then offer up to 2 slots.
Step 1: Offer dates (check_next_available) OR check the date they said
Step 2: Caller picks time → confirm it back
Step 3: Ask reason / service type
Step 4: Ask full name — "May I have your full name please?"
Step 5: If unsure of spelling → "Could you spell that for me?" Read back: "So that's R-A-J-E-S-H, Rajesh — is that right?"
Step 6: Ask phone number — "And your phone number?"
Step 7: Read back ALL details — name, date, time, service, phone — then ask "Is everything correct?"
Step 8: Only after confirmation → call book_appointment

═══ NAME RULES ═══
Malaysian names: Malay (Ahmad bin Zainal), Chinese (Tan Wei Ming), Indian (Priya a/p Krishnan).
Always spell out the name letter by letter and confirm. Never assume spelling from pronunciation.

═══ GUARDRAILS ═══
• Never give medical advice. "I'm not able to advise on medical matters — please speak to our doctor."
• Never discuss pricing. "For pricing, our staff will be happy to assist you."
• Emergency: "If this is a medical emergency, please call 999 immediately. I can also connect you to our staff."
• Never invent availability — always call check_availability or check_next_available first.
• Never book without confirming name, phone, date, time, and service.
• Never reveal other patients' information.
• If caller is rude or abusive: politely warn once, then transfer to human.
• For anything outside appointment booking → answer_faq first, then transfer_to_human if needed.

═══ LANGUAGE ═══
Detect caller's language from their FIRST message. Respond in that same language throughout.
If caller switches language mid-call, switch immediately. Supported: English, Bahasa Melayu, Tamil, Mandarin.""",

    "ms": """\
Awak Maya, resepsionis {business_name} yang mesra dan profesional.
Waktu klinik: {business_hours} WMT, Isnin hingga Sabtu. Tutup Ahad dan cuti umum.
Hari ini: {current_date} ({current_day}). Esok: {tomorrow_date} ({tomorrow_day}). Pukul sekarang: {current_time} WMT.

═══ CARA BERCAKAP ═══
• Telefon — 1 hingga 2 ayat SAHAJA setiap jawapan. Mesra, ringkas, semula jadi.
• Gaya Melayu Malaysia semula jadi: "Boleh, boleh.", "Jap ye, saya semak dulu.", "Okay, noted.", "Tak apa.", "Maaf, waktu tu dah penuh.", "Baik, tiada masalah."
• SATU soalan setiap giliran — jangan tanya dua perkara sekali gus.
• Tiada senarai atau bullet point — awak bercakap bukan menulis.
• Alamat formal: Encik (lelaki) / Puan (perempuan) / Cik (wanita muda belum berkahwin). Tanya kalau tak pasti.

═══ PERATURAN TARIKH & MASA ═══
• Untuk ALAT: guna format YYYY-MM-DD sahaja. Jangan hantar "esok", "Jumaat" — hanya tarikh tepat.
• "hari ini" = {today_date}, "esok" = {tomorrow_date}. Kira dari {current_day} untuk selesaikan nama hari.
• Untuk BERCAKAP DENGAN PEMANGGIL: sebut tarikh secara semula jadi — "Khamis dua puluh dua Mei" bukan "2025-05-22". Sebut masa sebagai "pukul sepuluh pagi" atau "pukul dua setengah petang".

═══ ALIRAN TEMPAHAN (satu langkah setiap giliran) ═══
Kalau pemanggil nak buat temujanji tapi tak sebut tarikh → panggil check_next_available dulu, tawarkan sehingga 2 tarikh.
Kalau pemanggil sebut tarikh → panggil check_availability, tawarkan sehingga 2 slot.
Langkah 1: Tawarkan tarikh (check_next_available) ATAU semak tarikh yang disebutkan
Langkah 2: Pemanggil pilih masa → ulang balik untuk sahkan
Langkah 3: Tanya sebab / jenis perkhidmatan
Langkah 4: Tanya nama penuh — "Boleh saya tahu nama penuh Encik/Puan?"
Langkah 5: Kalau tak pasti ejaan → "Boleh tolong ejakan nama tu?" Baca semula: "Jadi A-H-M-A-D — betul?"
Langkah 6: Tanya nombor telefon — "Dan nombor telefon Encik/Puan?"
Langkah 7: Baca semula SEMUA butiran — nama, tarikh, masa, perkhidmatan, telefon — tanya "Semua betul?"
Langkah 8: Hanya selepas pemanggil sahkan → panggil book_appointment

═══ PAGAR KESELAMATAN ═══
• Jangan bagi nasihat perubatan. "Saya tak boleh bagi nasihat perubatan — sila berjumpa doktor kami."
• Jangan bincang harga. "Untuk maklumat harga, petugas kami akan bantu."
• Kecemasan: "Kalau ini kecemasan perubatan, sila hubungi 999 sekarang."
• Jangan reka ketersediaan — selalu semak dulu.
• Jangan tempah tanpa sahkan semua butiran.
• Jangan dedahkan maklumat pesakit lain.

═══ BAHASA ═══
Kesan bahasa pemanggil dari mesej PERTAMA. Jawab dalam bahasa yang sama sepanjang perbualan.
Kalau pemanggil tukar bahasa, tukar segera.
ALAT: check_availability, check_next_available, book_appointment, cancel_appointment, reschedule_appointment, answer_faq, transfer_to_human.""",

    "ta": """\
நீங்கள் {business_name}-இன் நட்பான வரவேற்பாளர் Maya.
கிளினிக் நேரம்: {business_hours} MYT, திங்கள் முதல் சனி வரை. ஞாயிறு மற்றும் பொது விடுமுறை மூடப்பட்டிருக்கும்.
இன்று: {current_date} ({current_day}). நாளை: {tomorrow_date} ({tomorrow_day}). இப்போது: {current_time} MYT.

═══ பேசும் விதம் ═══
• தொலைபேசி — ஒரு முறைக்கு அதிகபட்சம் 1 முதல் 2 வாக்கியங்கள். அன்பாக, சுருக்கமாக, இயற்கையாக.
• மலேசிய தமிழ் பாணி: "சரி, பார்க்கிறேன்.", "ஒரு நிமிஷம்.", "முடியும், முடியும்.", "பரவாயில்லை.", "மன்னிக்கவும், அந்த நேரம் போய்விட்டது."
• ஒரு முறைக்கு ஒரே கேள்வி — இரண்டு விஷயங்களை ஒரே நேரத்தில் கேட்காதீர்கள்.
• மரியாதையான முகவரி: அய்யா (ஆண்) / அம்மா (பெண்).

═══ தேதி மற்றும் நேர விதிகள் ═══
• கருவிகளுக்கு: YYYY-MM-DD வடிவமை மட்டுமே. "நாளை", "வெள்ளி" என்று அனுப்பாதீர்கள்.
• "இன்று" = {today_date}, "நாளை" = {tomorrow_date}.
• பேசும்போது: "மே மாதம் இருபத்திரண்டாம் தேதி வியாழக்கிழமை" என்று இயற்கையாகச் சொல்லுங்கள்.

═══ முன்பதிவு படிகள் (ஒரு முறைக்கு ஒரு படி) ═══
தேதி சொல்லவில்லை → check_next_available அழைத்து 2 தேதிகள் வழங்கவும்.
தேதி சொன்னால் → check_availability அழைத்து 2 slot வழங்கவும்.
படி 1: தேதிகள் வழங்கவும் / சரிபார்க்கவும்
படி 2: நேரம் தேர்வு → திரும்ப சொல்லி உறுதிப்படுத்தவும்
படி 3: சேவை / வருவதற்கான காரணம் கேளுங்கள்
படி 4: "பெயர் சொல்லுங்கள் அய்யா/அம்மா?"
படி 5: "Spelling சொல்லுங்களேன்?" → "V-I-J-A-Y — சரியா?"
படி 6: "தொலைபேசி எண் சொல்லுங்கள்?"
படி 7: அனைத்து விவரங்களையும் சொல்லி "எல்லாம் சரியா?" என்று கேளுங்கள்
படி 8: உறுதிப்படுத்திய பின்பு மட்டுமே → book_appointment

═══ பாதுகாப்பு விதிகள் ═══
• மருத்துவ ஆலோசனை வழங்காதீர்கள். "அதற்கு நம் டாக்டரிடம் பேசுங்கள்."
• விலை பற்றி பேசாதீர்கள். "விலை விவரங்களுக்கு நம் ஊழியர் உதவுவார்கள்."
• அவசரகாலம்: "மருத்துவ அவசரநிலையா? 999 அழைக்கவும்."
• முன்பதிவு இல்லாமல் slot கண்டுபிடிக்காதீர்கள் — எப்போதும் முதலில் சரிபார்க்கவும்.

═══ மொழி ═══
முதல் செய்தியிலிருந்தே மொழியை கண்டறிந்து அதே மொழியில் பதில் சொல்லவும். மொழி மாறினால் உடனே பின்பற்றவும்.
கருவிகள்: check_availability, check_next_available, book_appointment, cancel_appointment, reschedule_appointment, answer_faq, transfer_to_human.""",

    "zh": """\
你是{business_name}亲切的语音接待员Maya。
诊所时间：{business_hours} 马来西亚时间，周一至周六。周日及公共假日休息。
今天：{current_date}（{current_day}）。明天：{tomorrow_date}（{tomorrow_day}）。现在：{current_time} 马来西亚时间。

═══ 说话方式 ═══
• 电话通话——每次回复最多1到2句话。亲切、简洁、自然。
• 马来西亚华语风格：「好的，没问题。」「我查一下哦。」「稍等啊。」「可以，可以。」「不好意思，那个时段已满了。」「没关系。」
• 每次只问一个问题——不要一次问两件事。
• 使用敬语「您」。不要使用列表或符号——您在说话，不是打字。

═══ 日期与时间规则 ═══
• 调用工具时：只用YYYY-MM-DD格式。不要传「明天」「星期五」——只传确切日期。
• 「今天」= {today_date}，「明天」= {tomorrow_date}。从{current_day}开始数算任何日期名称。
• 与来电者交谈时：自然地说日期——「五月二十二号星期四」而不是「2025-05-22」。时间说「上午十点」或「下午两点半」。

═══ 预约流程（每轮一步，严格执行）═══
若来电者想预约但未说日期 → 先调用check_next_available，提供最多2个日期。
若来电者说了日期 → 调用check_availability，提供最多2个时段。
第1步：提供日期（check_next_available）或查询来电者说的日期
第2步：来电者选时间 → 复述确认
第3步：询问就诊原因/服务类型
第4步：「请问您怎么称呼？」
第5步：不确定拼写时 → 「可以拼一下名字吗？」回读：「所以是T-A-N伟明——对吗？」
第6步：「您的电话号码是？」
第7步：复述全部信息——姓名、日期、时间、服务、电话——「以上信息都正确吗？」
第8步：来电者确认后才调用book_appointment

═══ 安全护栏 ═══
• 不提供医疗建议。「医疗方面的问题请咨询我们的医生。」
• 不讨论价格。「收费详情我们的工作人员会为您解答。」
• 紧急情况：「如果是医疗紧急情况，请立即拨打999。」
• 不捏造预约时段——必须先查询。
• 未确认全部信息前不得预约。
• 不透露其他病人的信息。

═══ 语言 ═══
从来电者第一条消息判断语言，全程用该语言回复。来电者切换语言时立即跟随。
工具：check_availability、check_next_available、book_appointment、cancel_appointment、reschedule_appointment、answer_faq、transfer_to_human。""",
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


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        tod = "Good morning"
    elif hour < 17:
        tod = "Good afternoon"
    else:
        tod = "Good evening"
    return f"{tod}, {config.business_name}, Maya speaking. How may I help you?"


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
        self._conv_state: dict = {"step": 0, "lang": "en", "collected": {}}
        super().__init__(instructions=_build_prompt("en"))

    # ------------------------------------------------------------------
    # TTS: ElevenLabs turbo per language → EdgeTTS fallback
    # Collect text first so we can retry cleanly with EdgeTTS on failure.
    # ------------------------------------------------------------------

    async def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings):
        # Collect all LLM text before sending to TTS — enables clean retry
        text_chunks: list[str] = []
        async for chunk in text:
            text_chunks.append(chunk)

        if not text_chunks:
            return

        lang = self._detected_lang
        primary = self._tts_engines.get(lang, self._tts_engines["en"])
        fallback = self._tts_fallbacks.get(lang, self._tts_fallbacks["en"])

        for attempt, tts_engine in enumerate([primary, fallback]):
            tts_to_use = tts_engine
            if not tts_to_use.capabilities.streaming:
                tts_to_use = tts_module.StreamAdapter(
                    tts=tts_to_use,
                    sentence_tokenizer=tokenize.basic.SentenceTokenizer(),
                )
            try:
                async with tts_to_use.stream() as stream:
                    for chunk in text_chunks:
                        stream.push_text(chunk)
                    stream.end_input()
                    async for ev in stream:
                        yield ev.frame
                return
            except Exception as exc:
                if attempt == 0:
                    log_fallback("tts", type(primary).__name__, type(fallback).__name__, str(exc))
                else:
                    logger.error("EdgeTTS fallback also failed lang=%s: %s", lang, exc)
                    raise

    # ------------------------------------------------------------------
    # Language detection + hallucination filtering
    # ------------------------------------------------------------------

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        try:
            text = (new_message.text_content or "").strip()
            logger.info("User: %r | lang=%s", text[:80], self._detected_lang)

            if not text or _PUNCT_ONLY_RE.match(text):
                logger.warning("Dropping punct-only: %r", text)
                new_message.content = []
                return

            if _HALLUCINATION_RE.search(text):
                logger.warning("Dropping hallucination: %r", text)
                new_message.content = []
                return

            words = text.split()
            if len(words) <= 1 and len(text) < 6:
                logger.warning("Dropping echo/noise: %r", text)
                new_message.content = []
                return

            detected = lang_handler.detect_language(text)
            if detected and detected != self._detected_lang:
                log_language_switch(self._detected_lang, detected)
                self._detected_lang = detected
                self.update_instructions(_build_prompt(detected))
                logger.info("Language → %s", detected)

            self._conv_state["lang"] = self._detected_lang
            if self._db and self._room_id:
                await self._db.save_conversation_state(self._room_id, self._conv_state)

        except Exception:
            logger.exception("on_user_turn_completed error")

        await super().on_user_turn_completed(turn_ctx, new_message)

    # ------------------------------------------------------------------
    # Function tools
    # ------------------------------------------------------------------

    @function_tool
    async def check_availability(
        self,
        date: Annotated[str, "Date in YYYY-MM-DD format"],
    ) -> str:
        """Check available appointment slots for a specific date."""
        with timed("check_availability"):
            raw = await self.bm.get_slots(date)

        if raw.startswith("no_slots|"):
            _, d = raw.split("|", 1)
            from datetime import datetime as _dt
            spoken = _dt.strptime(d, "%Y-%m-%d").strftime("%A the %-d of %B") if sys.platform != "win32" else _dt.strptime(d, "%Y-%m-%d").strftime("%A %d %B")
            return f"No slots available on {spoken}. Suggest checking another date."

        _, date_str, times = raw.split("|", 2)
        slot_list = times.split(",")[:2]  # offer max 2 slots
        from datetime import datetime as _dt
        try:
            spoken_date = _dt.strptime(date_str, "%Y-%m-%d").strftime("%A %d %B")
        except Exception:
            spoken_date = date_str
        return f"Available on {spoken_date}: {' and '.join(slot_list)}. Which time suits you?"

    @function_tool
    async def check_next_available(
        self,
        days_ahead: Annotated[int, "How many days ahead to search, default 7"] = 7,
    ) -> str:
        """Find the next available appointment dates when caller hasn't named a date."""
        with timed("check_next_available"):
            raw = await self.bm.get_next_available(days_to_check=days_ahead)

        if raw.startswith("no_upcoming|"):
            return "No available slots in the next 7 days. Please suggest the caller call back or transfer to staff."

        _, data = raw.split("|", 1)
        entries = data.split(";")
        results = []
        from datetime import datetime as _dt
        for entry in entries:
            date_str, times = entry.split(": ", 1)
            slot_list = times.split(",")[:2]
            try:
                spoken_date = _dt.strptime(date_str, "%Y-%m-%d").strftime("%A %d %B")
            except Exception:
                spoken_date = date_str
            results.append(f"{spoken_date} at {' or '.join(slot_list)}")
        return "Upcoming availability: " + "; ".join(results) + ". Offer these options to the caller."

    @function_tool
    async def book_appointment(
        self,
        name: Annotated[str, "Customer full name — confirmed spelling"],
        phone: Annotated[str, "Phone number e.g. 0123456789 or +60123456789"],
        date: Annotated[str, "Appointment date YYYY-MM-DD"],
        time: Annotated[str, "Appointment time HH:MM (24-hour)"],
        service: Annotated[str, "Service type e.g. General Consultation"],
    ) -> str:
        """Book appointment. Only call after all details are confirmed by the caller."""
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
        question: Annotated[str, "Question about clinic hours, location, payment, parking, etc."],
    ) -> str:
        """Answer common questions about the clinic."""
        return await self.bm.get_faq_answer(question)

    @function_tool
    async def transfer_to_human(
        self,
        reason: Annotated[str, "Why a human staff member is needed"],
    ) -> str:
        """Transfer to human staff for anything outside Maya's scope."""
        log_transfer(reason)
        if self._db and self._room_id:
            await self._db.clear_conversation_state(self._room_id)
        responses = {
            "en": "Sure, please hold — I'll connect you to our staff now.",
            "ms": "Baik, sila tunggu sebentar — saya sambungkan ke petugas kami.",
            "ta": "சரி, ஒரு நிமிஷம் — ஊழியரிடம் இணைக்கிறேன்.",
            "zh": "好的，请稍候——我为您转接工作人员。",
        }
        return responses.get(self._detected_lang, responses["en"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Prewarm — runs once per worker process before any call arrives.
# Loads heavy models (VAD weights) into shared memory so the first
# caller gets a warm agent instead of waiting for model download.
# ---------------------------------------------------------------------------

def prewarm(proc: JobProcess) -> None:
    try:
        proc.userdata["vad"] = silero.VAD.load(
            activation_threshold=0.55,
            min_speech_duration=0.15,
            min_silence_duration=0.65,
        )
        logger.info("Prewarm complete — VAD loaded")
    except Exception:
        # Log clearly and continue — entrypoint will load VAD lazily per call.
        logger.exception("Prewarm failed; VAD will be loaded on first call")


# ---------------------------------------------------------------------------
# Entry point — called once per incoming call/room
# ---------------------------------------------------------------------------

async def entrypoint(ctx: JobContext) -> None:
    import time as _time

    # ── Windows: silence benign asyncio ConnectionResetError (WinError 10054) ──
    if sys.platform == "win32":
        loop = asyncio.get_running_loop()
        _orig = loop.get_exception_handler() or loop.default_exception_handler
        def _win_handler(lp, ctx_data):
            if isinstance(ctx_data.get("exception"), ConnectionResetError):
                return
            (_orig(ctx_data) if callable(_orig) else lp.default_exception_handler(ctx_data))
        loop.set_exception_handler(_win_handler)

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    room_name: str = ctx.room.name if ctx.room else "unknown"
    job_id: str = str(ctx.job.id) if ctx.job else "-"

    # ── Service health check ──────────────────────────────────────────────
    db = BookingDatabase()
    bm_temp = BookingManager()
    mode = await determine_mode(db, bm_temp._gcal)
    logger.info("Service mode: %s | room: %s", mode.value, room_name)

    # ── Session tracking ──────────────────────────────────────────────────
    session_record = await db.create_voice_session(livekit_room_id=room_name)
    session_db_id = session_record["id"] if session_record else None
    session_start = _time.monotonic()
    log_session_start(room_id=room_name, job_id=job_id)

    # ── VAD: reuse prewarmed instance (no model reload per call) ──────────
    vad: silero.VAD = ctx.proc.userdata.get("vad") or silero.VAD.load(
        activation_threshold=0.55,
        min_speech_duration=0.15,
        min_silence_duration=0.65,
    )

    # ── STT: ElevenLabs Scribe → Deepgram Nova-3 → Groq Whisper ──────────
    stt_engine = stt_module.FallbackAdapter(
        [
            elevenlabs.STT(api_key=config.elevenlabs_api_key, use_realtime=True),
            deepgram.STT(api_key=config.deepgram_api_key, model="nova-3"),
            # Groq Whisper is non-streaming — wrap with StreamAdapter + prewarmed VAD
            stt_module.StreamAdapter(
                stt=lk_openai.STT(
                    model="whisper-large-v3-turbo",
                    api_key=config.groq_api_key,
                    base_url="https://api.groq.com/openai/v1",
                ),
                vad=vad,
            ),
        ]
    )

    # ── LLM: Groq plugin (handles Groq tool-schema validation natively) ───
    llm_engine = llm_module.FallbackAdapter(
        [
            lk_groq.LLM(model="llama-3.3-70b-versatile", api_key=config.groq_api_key),
            lk_groq.LLM(model="llama-3.1-8b-instant",    api_key=config.groq_api_key),
        ]
    )

    # ── TTS: ElevenLabs turbo, one voice per language ─────────────────────
    # Do NOT pass language= — voice IDs may reject specific language codes
    # causing immediate WebSocket disconnect. eleven_turbo_v2_5 auto-detects
    # language from text. streaming_latency=3 → ~250ms first-audio vs ~1s.
    tts_engines = {
        lang: elevenlabs.TTS(
            voice_id=voice_id,
            model="eleven_turbo_v2_5",
            api_key=config.elevenlabs_api_key,
            streaming_latency=3,
        )
        for lang, voice_id in ELEVENLABS_VOICES.items()
    }

    # ── TTS fallback: Edge TTS free regional voices ───────────────────────
    tts_fallbacks = {lang: EdgeTTS(language=lang) for lang in ELEVENLABS_VOICES}

    # ── Agent session ─────────────────────────────────────────────────────
    session = AgentSession(
        stt=stt_engine,
        llm=llm_engine,
        tts=tts_engines["en"],
        vad=vad,

        # VAD-based endpointing — no separate inference subprocess required.
        # MultilingualModel was removed because it registers an inference runner
        # that spawns a subprocess which OOMs on constrained containers.
        # The generous min/max delays below compensate for multilingual pauses.
        min_endpointing_delay=0.7,
        max_endpointing_delay=4.0,

        # "ya", "okay", "mm", "betul", "boleh", "lah" = backchannels, not
        # interruptions. Require 0.8 s of real speech AND ≥ 3 words.
        allow_interruptions=True,
        min_interruption_duration=0.8,
        min_interruption_words=3,

        # Resume agent speech if the "interruption" was just a backchannel.
        false_interruption_timeout=2.5,
        resume_false_interruption=True,

        # Start LLM + TTS speculatively before EOU is confirmed.
        # Biggest latency win — shaves ~300–500 ms off each response.
        preemptive_generation=True,

        # Brief natural pause between consecutive agent utterances.
        min_consecutive_speech_delay=0.3,

        # Allow check_availability → book_appointment in a single LLM turn.
        max_tool_steps=5,
    )

    # ── Resume previous session if state exists ───────────────────────────
    existing_state = await db.load_conversation_state(room_name)
    resume_lang = existing_state.get("lang", "en") if existing_state else "en"
    resume_notice: Optional[str] = None
    if existing_state:
        resume_notice = {
            "en": "I see we were in the middle of something — let me continue from where we left off.",
            "ms": "Nampaknya kita terganggu tadi — saya sambung semula.",
            "ta": "நாம் நடுவில் இருந்தோம் — தொடர்கிறேன்.",
            "zh": "我们之前被中断了——继续为您服务。",
        }.get(resume_lang, "Let me pick up where we left off.")

    agent = MayaAgent(
        tts_engines=tts_engines,
        tts_fallbacks=tts_fallbacks,
        db=db,
        room_id=room_name,
    )
    if existing_state:
        agent._conv_state = existing_state
        agent._detected_lang = resume_lang
        agent.update_instructions(_build_prompt(resume_lang))

    # ── Start session with noise cancellation ─────────────────────────────
    # BVCTelephony = Krisp model optimised for inbound phone/SIP callers.
    # BVC = general headset/earbud model for WebRTC web callers.
    # Switch to noise_cancellation.BVC() if using the LiveKit web playground.
    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # ── Opening message ───────────────────────────────────────────────────
    if mode == ServiceMode.EMERGENCY:
        await session.say(mode_notice(mode, "en"))
    else:
        if mode == ServiceMode.DEGRADED:
            await session.say(mode_notice(mode, "en"))
        await session.say(resume_notice if resume_notice else _greeting())

    logger.info("Maya ready | room=%s | mode=%s | job=%s", room_name, mode.value, job_id)

    # ── Cleanup on disconnect ─────────────────────────────────────────────
    @ctx.room.on("disconnected")
    def _on_disconnect(*_):
        duration = _time.monotonic() - session_start
        log_session_end(room_id=room_name, duration_sec=duration)
        asyncio.create_task(db.end_voice_session(session_db_id or ""))
        asyncio.create_task(db.clear_conversation_state(room_name))


# ---------------------------------------------------------------------------
# Startup validation — runs before cli.run_app()
# ---------------------------------------------------------------------------

def _startup_checks() -> None:
    """Validate environment and log resource state before the worker starts."""
    _REQUIRED_ENV = [
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "ELEVENLABS_API_KEY",
        "DEEPGRAM_API_KEY",
        "GROQ_API_KEY",
    ]
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        logger.critical("Missing required environment variables: %s", missing)
        sys.exit(1)
    logger.info("Environment OK — all required variables present")

    # Log available memory so OOM issues are visible in Railway logs.
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith(("MemTotal", "MemAvailable")):
                    logger.info("Memory: %s", line.strip())
    except OSError:
        pass  # not Linux

    # Raise the file-descriptor limit to avoid EMFILE under load.
    try:
        import resource as _resource
        soft, hard = _resource.getrlimit(_resource.RLIMIT_NOFILE)
        target = min(65536, hard)
        if soft < target:
            _resource.setrlimit(_resource.RLIMIT_NOFILE, (target, hard))
            logger.info("File descriptor limit raised: %d → %d", soft, target)
        else:
            logger.info("File descriptor limit: %d (hard=%d)", soft, hard)
    except (ImportError, ValueError, OSError):
        pass  # Windows or unprivileged container


# ---------------------------------------------------------------------------
# Worker — production-ready configuration
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _startup_checks()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,

            # Load VAD model before first call so callers never wait for it
            prewarm_fnc=prewarm,

            # 0 idle processes: spawn on first call, not at startup.
            # Avoids OOM-killing the subprocess while loading torch/Silero
            # in Railway's memory-constrained container.
            num_idle_processes=0,

            # 60 s gives torch + plugin imports time to finish before the
            # framework declares the subprocess dead (default is only 10 s).
            initialize_process_timeout=60.0,

            # Stop accepting new calls at 70% CPU/memory load
            load_threshold=0.7,

            # Named agent — enables explicit dispatch from your backend
            agent_name="maya-receptionist",

            # Graceful shutdown: finish active calls before stopping (30 min max)
            drain_timeout=1800,
        )
    )
