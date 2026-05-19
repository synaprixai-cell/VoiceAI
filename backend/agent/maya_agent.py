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
