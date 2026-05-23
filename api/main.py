"""
VoiceAI Backend API
─────────────────────────────────────────────────
POST /api/voice-token   — generate LiveKit JWT for web clients
POST /livekit/webhook   — receive LiveKit room events
GET  /api/bookings      — list bookings (admin)
PATCH /api/bookings/:id — update booking status (admin)
POST /api/sip/dial      — handle inbound SIP/phone calls
GET  /health            — health check
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# Allow imports from project root (config, database, etc.)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from config import Config
from database import BookingDatabase

logger = logging.getLogger(__name__)
config = Config()

app = FastAPI(title="VoiceAI Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.getenv("FRONTEND_URL", ""),
        "http://localhost:3000",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _supabase():
    """Return a Supabase client using the same credentials as the agent."""
    from supabase import create_client
    return create_client(config.supabase_url, config.supabase_key)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "service": "voiceai-backend",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# 1. Token Generation
# ---------------------------------------------------------------------------

@app.post("/api/voice-token")
async def generate_voice_token(request: Request):
    """
    Generate a LiveKit JWT so a web client can join a voice room.
    Body: { "participant_name": "...", "tenant_id": "..." (optional) }
    Returns: { "token": "eyJ...", "room_name": "voice-...", "url": "wss://..." }
    """
    try:
        from livekit.api import AccessToken, VideoGrants
    except ImportError:
        raise HTTPException(500, "livekit-api package not installed. Add livekit-api to requirements.txt.")

    body = await request.json()
    participant_name: str = body.get("participant_name", "Caller")
    tenant_id: str = body.get("tenant_id", config.tenant_id)

    if not config.livekit_api_key or not config.livekit_api_secret:
        raise HTTPException(500, "LIVEKIT_API_KEY / LIVEKIT_API_SECRET not configured.")

    room_name = f"voice-{tenant_id[:8]}-{int(time.time())}"

    token = (
        AccessToken(api_key=config.livekit_api_key, api_secret=config.livekit_api_secret)
        .with_identity(participant_name)
        .with_name(participant_name)
        .with_grants(VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True))
        .with_ttl(timedelta(hours=1))
    )

    # Log the new session in Supabase (best-effort)
    try:
        sb = _supabase()
        await asyncio.to_thread(
            lambda: sb.table("voice_sessions").insert({
                "tenant_id": tenant_id,
                "livekit_room_id": room_name,
                "status": "created",
            }).execute()
        )
    except Exception as exc:
        logger.warning("Could not log voice session: %s", exc)

    return {
        "token": token.to_jwt(),
        "room_name": room_name,
        "url": config.livekit_url,
    }


# ---------------------------------------------------------------------------
# 2. LiveKit Webhook
# ---------------------------------------------------------------------------

@app.post("/livekit/webhook")
async def livekit_webhook(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """
    Receive LiveKit room lifecycle events.
    LiveKit signs the body with LIVEKIT_API_SECRET — we verify before processing.
    """
    body_bytes = await request.body()
    body_str = body_bytes.decode()

    # Verify signature
    try:
        from livekit.api import WebhookReceiver
        receiver = WebhookReceiver(
            api_key=config.livekit_api_key,
            api_secret=config.livekit_api_secret,
        )
        event = receiver.receive(body_str, authorization)
    except Exception as exc:
        logger.warning("Webhook verification failed: %s", exc)
        raise HTTPException(401, "Invalid webhook signature")

    event_type: str = event.event
    room_name: Optional[str] = event.room.name if event.room else None
    logger.info("LiveKit event: %s | room: %s", event_type, room_name)

    sb = _supabase()

    # Log every event for debugging / analytics
    try:
        await asyncio.to_thread(
            lambda: sb.table("livekit_events").insert({
                "event_type": event_type,
                "room_name": room_name,
                "raw": body_str[:1000],
                "received_at": _now_iso(),
            }).execute()
        )
    except Exception as exc:
        logger.warning("Could not log livekit event: %s", exc)

    # Update voice_session status based on event
    if room_name:
        if event_type == "room_started":
            try:
                await asyncio.to_thread(
                    lambda: sb.table("voice_sessions")
                    .update({"status": "active"})
                    .eq("livekit_room_id", room_name)
                    .execute()
                )
            except Exception as exc:
                logger.warning("room_started update failed: %s", exc)

        elif event_type == "room_finished":
            try:
                await asyncio.to_thread(
                    lambda: sb.table("voice_sessions")
                    .update({"status": "ended", "ended_at": _now_iso()})
                    .eq("livekit_room_id", room_name)
                    .execute()
                )
            except Exception as exc:
                logger.warning("room_finished update failed: %s", exc)

    return {"status": "ok", "event": event_type}


# ---------------------------------------------------------------------------
# 3. Admin — Bookings
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"pending", "confirmed", "cancelled", "completed", "rescheduled"}


@app.get("/api/bookings")
async def list_bookings(
    tenant_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """
    List bookings with contact name and phone joined.
    Query params: tenant_id, status, limit
    """
    tid = tenant_id or config.tenant_id
    sb = _supabase()

    try:
        query = (
            sb.table("bookings")
            .select("id, scheduled_at, service_type, status, source, created_at, contacts(name, phone)")
            .eq("tenant_id", tid)
        )
        if status:
            query = query.eq("status", status)

        result = await asyncio.to_thread(
            lambda: query.order("scheduled_at", desc=True).limit(limit).execute()
        )
        return {"bookings": result.data, "count": len(result.data)}
    except Exception as exc:
        logger.error("list_bookings error: %s", exc)
        raise HTTPException(500, str(exc))


@app.patch("/api/bookings/{booking_id}")
async def update_booking(booking_id: str, request: Request):
    """
    Update a booking's status.
    Body: { "status": "cancelled" | "confirmed" | "completed" | ... }
    """
    body = await request.json()
    new_status: Optional[str] = body.get("status")

    if not new_status:
        raise HTTPException(400, "status field required")
    if new_status not in _VALID_STATUSES:
        raise HTTPException(400, f"status must be one of: {sorted(_VALID_STATUSES)}")

    sb = _supabase()
    try:
        result = await asyncio.to_thread(
            lambda: sb.table("bookings")
            .update({"status": new_status, "updated_at": _now_iso()})
            .eq("id", booking_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "Booking not found")
        return {"success": True, "booking": result.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_booking error: %s", exc)
        raise HTTPException(500, str(exc))


# ---------------------------------------------------------------------------
# 4. SIP / Inbound Phone Calls
# ---------------------------------------------------------------------------

@app.post("/api/sip/dial")
async def sip_inbound(request: Request):
    """
    Called by your SIP provider (Twilio, Vonage, LiveKit SIP trunk) when a
    phone call arrives. Creates a voice session record and returns the LiveKit
    room name so the SIP bridge knows where to send the call.
    Body: { "phone_number": "+60123456789", "caller_name": "..." }
    """
    body = await request.json()
    phone_number: str = body.get("phone_number", "unknown")
    caller_name: str = body.get("caller_name", "Phone Caller")
    tenant_id: str = body.get("tenant_id", config.tenant_id)

    room_name = f"sip-{int(time.time())}"

    sb = _supabase()
    try:
        await asyncio.to_thread(
            lambda: sb.table("voice_sessions").insert({
                "tenant_id": tenant_id,
                "livekit_room_id": room_name,
                "status": "ringing",
            }).execute()
        )
    except Exception as exc:
        logger.warning("Could not log SIP session: %s", exc)

    logger.info("SIP inbound | phone=%s | room=%s", phone_number, room_name)

    return {
        "room_name": room_name,
        "livekit_url": config.livekit_url,
        "status": "dispatched",
    }


# ---------------------------------------------------------------------------
# Run directly for local dev: python api/main.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True,
    )
