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
