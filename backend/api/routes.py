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
