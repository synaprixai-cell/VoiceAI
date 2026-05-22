import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # LiveKit
    livekit_url: str = os.getenv("LIVEKIT_URL", "")
    livekit_api_key: str = os.getenv("LIVEKIT_API_KEY", "")
    livekit_api_secret: str = os.getenv("LIVEKIT_API_SECRET", "")

    # Supabase
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_KEY", ""))

    # Tenant
    tenant_id: str = os.getenv("TENANT_ID", "")

    # STT / TTS / LLM API keys
    deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "")

    # Business settings
    business_name: str = os.getenv("BUSINESS_NAME", "My Clinic")
    business_hours_start: str = os.getenv("BUSINESS_HOURS_START", "09:00")
    business_hours_end: str = os.getenv("BUSINESS_HOURS_END", "18:00")
    timezone: str = os.getenv("TIMEZONE", "Asia/Kuala_Lumpur")
    business_phone: str = os.getenv("BUSINESS_PHONE", "")
    business_address: str = os.getenv("BUSINESS_ADDRESS", "")

    # Google Calendar
    google_calendar_id: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    google_token_file: str = os.getenv("GOOGLE_TOKEN_FILE", "google_token.json")
