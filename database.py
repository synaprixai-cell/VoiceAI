import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from supabase import create_client, Client
from config import Config

logger = logging.getLogger(__name__)
config = Config()


class BookingDatabase:
    """
    Wraps all Supabase operations for the voice receptionist.
    Uses the existing schema: contacts, bookings, voice_sessions, call_logs.
    Only availability_slots is a new table added for this agent.
    """

    def __init__(self):
        self.client: Client = create_client(config.supabase_url, config.supabase_key)
        self.tenant_id: str = config.tenant_id

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    async def find_or_create_contact(
        self, phone: str, name: Optional[str] = None, language: str = "en"
    ) -> Dict:
        def _find():
            return (
                self.client.table("contacts")
                .select("id,phone,name,language_preference")
                .eq("tenant_id", self.tenant_id)
                .eq("phone", phone)
                .limit(1)
                .execute()
            )

        resp = await asyncio.to_thread(_find)
        if resp.data:
            return resp.data[0]

        # Create new contact
        def _create():
            return (
                self.client.table("contacts")
                .insert({
                    "tenant_id": self.tenant_id,
                    "phone": phone,
                    "name": name,
                    "language_preference": language,
                })
                .execute()
            )

        create_resp = await asyncio.to_thread(_create)
        return create_resp.data[0]

    # ------------------------------------------------------------------
    # Availability slots
    # ------------------------------------------------------------------

    async def check_availability(self, date: str, time: str) -> bool:
        def _sync():
            return (
                self.client.table("availability_slots")
                .select("id")
                .eq("slot_date", date)
                .eq("slot_time", time)
                .eq("is_available", True)
                .execute()
            )

        resp = await asyncio.to_thread(_sync)
        return len(resp.data) > 0

    async def get_available_slots(self, date: str) -> List[Dict]:
        def _sync():
            return (
                self.client.table("availability_slots")
                .select("slot_time")
                .eq("slot_date", date)
                .eq("is_available", True)
                .order("slot_time")
                .execute()
            )

        resp = await asyncio.to_thread(_sync)
        return resp.data

    async def _mark_slot(self, date: str, time: str, available: bool) -> None:
        def _sync():
            return (
                self.client.table("availability_slots")
                .update({"is_available": available})
                .eq("slot_date", date)
                .eq("slot_time", time)
                .execute()
            )

        try:
            await asyncio.to_thread(_sync)
        except Exception as e:
            logger.warning(f"Could not update slot availability: {e}")

    # ------------------------------------------------------------------
    # Bookings  (uses existing schema: contact_id, scheduled_at, etc.)
    # ------------------------------------------------------------------

    async def create_booking(
        self,
        contact_id: str,
        scheduled_at: str,   # ISO 8601 e.g. "2025-05-22T10:00:00+08:00"
        service_type: str,
        call_log_id: Optional[str] = None,
    ) -> Optional[Dict]:
        def _insert():
            payload = {
                "tenant_id": self.tenant_id,
                "contact_id": contact_id,
                "scheduled_at": scheduled_at,
                "service_type": service_type,
                "source": "voice",
                "status": "confirmed",
            }
            if call_log_id:
                payload["call_log_id"] = call_log_id
            return self.client.table("bookings").insert(payload).execute()

        resp = await asyncio.to_thread(_insert)
        if not resp.data:
            return None

        result = resp.data[0]

        # Mark slot as taken
        date_part = scheduled_at.split("T")[0]
        time_part = scheduled_at.split("T")[1][:5]
        await self._mark_slot(date_part, time_part, available=False)

        return result

    async def update_booking_gcal_event(self, booking_id: str, gcal_event_id: str) -> None:
        def _sync():
            return (
                self.client.table("bookings")
                .update({"gcal_event_id": gcal_event_id})
                .eq("id", booking_id)
                .execute()
            )
        try:
            await asyncio.to_thread(_sync)
        except Exception as e:
            logger.warning("Could not update gcal_event_id: %s", e)

    async def find_booking(
        self, phone: str, name: Optional[str] = None
    ) -> Optional[Dict]:
        """Find the most recent active booking by customer phone."""
        contact = await self.find_or_create_contact(phone, name)
        if not contact:
            return None

        def _sync():
            return (
                self.client.table("bookings")
                .select("id,scheduled_at,service_type,status,gcal_event_id")
                .eq("tenant_id", self.tenant_id)
                .eq("contact_id", contact["id"])
                .in_("status", ["confirmed", "rescheduled", "pending"])
                .order("scheduled_at", desc=True)
                .limit(1)
                .execute()
            )

        resp = await asyncio.to_thread(_sync)
        return resp.data[0] if resp.data else None

    async def cancel_booking(self, booking_id: str) -> bool:
        # Fetch first so we can free the slot
        def _fetch():
            return (
                self.client.table("bookings")
                .select("scheduled_at")
                .eq("id", booking_id)
                .limit(1)
                .execute()
            )

        fetch_resp = await asyncio.to_thread(_fetch)
        if not fetch_resp.data:
            return False

        scheduled_at: str = fetch_resp.data[0]["scheduled_at"]

        def _cancel():
            return (
                self.client.table("bookings")
                .update({
                    "status": "cancelled",
                    "cancelled_at": datetime.now(timezone.utc).isoformat(),
                    "cancelled_by": "voice_agent",
                })
                .eq("id", booking_id)
                .execute()
            )

        await asyncio.to_thread(_cancel)

        # Free slot
        date_part = scheduled_at.split("T")[0]
        time_part = scheduled_at.split("T")[1][:5]
        await self._mark_slot(date_part, time_part, available=True)
        return True

    async def reschedule_booking(
        self, booking_id: str, new_date: str, new_time: str
    ) -> bool:
        # Fetch old booking
        def _fetch():
            return (
                self.client.table("bookings")
                .select("scheduled_at")
                .eq("id", booking_id)
                .limit(1)
                .execute()
            )

        fetch_resp = await asyncio.to_thread(_fetch)
        if not fetch_resp.data:
            return False

        old_scheduled_at: str = fetch_resp.data[0]["scheduled_at"]
        new_scheduled_at = f"{new_date}T{new_time}:00+08:00"

        def _reschedule():
            return (
                self.client.table("bookings")
                .update({
                    "scheduled_at": new_scheduled_at,
                    "status": "rescheduled",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", booking_id)
                .execute()
            )

        await asyncio.to_thread(_reschedule)

        # Free old slot, mark new slot taken
        old_date = old_scheduled_at.split("T")[0]
        old_time = old_scheduled_at.split("T")[1][:5]
        await self._mark_slot(old_date, old_time, available=True)
        await self._mark_slot(new_date, new_time, available=False)
        return True

    # ------------------------------------------------------------------
    # Voice sessions & call logs
    # ------------------------------------------------------------------

    async def create_voice_session(self, livekit_room_id: str, contact_id: Optional[str] = None) -> Optional[Dict]:
        def _sync():
            return (
                self.client.table("voice_sessions")
                .insert({
                    "tenant_id": self.tenant_id,
                    "livekit_room_id": livekit_room_id,
                    "contact_id": contact_id,
                    "status": "active",
                })
                .execute()
            )

        try:
            resp = await asyncio.to_thread(_sync)
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.warning(f"Could not create voice session: {e}")
            return None

    async def end_voice_session(self, session_id: str, call_log_id: Optional[str] = None) -> None:
        def _sync():
            payload: Dict = {
                "status": "ended",
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }
            if call_log_id:
                payload["call_log_id"] = call_log_id
            return (
                self.client.table("voice_sessions")
                .update(payload)
                .eq("id", session_id)
                .execute()
            )

        try:
            await asyncio.to_thread(_sync)
        except Exception as e:
            logger.warning(f"Could not end voice session: {e}")

    async def create_call_log(
        self,
        contact_id: Optional[str],
        language: str,
        transcript: str,
        outcome: str,
        duration_sec: int = 0,
        escalated: bool = False,
        livekit_room_id: Optional[str] = None,
    ) -> Optional[Dict]:
        def _sync():
            return (
                self.client.table("call_logs")
                .insert({
                    "tenant_id": self.tenant_id,
                    "contact_id": contact_id,
                    "language_detected": language,
                    "language_used": language,
                    "transcript": transcript,
                    "outcome": outcome,
                    "duration_sec": duration_sec,
                    "escalated": escalated,
                    "source": "voice",
                    "livekit_room_id": livekit_room_id,
                })
                .execute()
            )

        try:
            resp = await asyncio.to_thread(_sync)
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.warning(f"Could not create call log: {e}")
            return None

    # ------------------------------------------------------------------
    # Conversation state persistence
    # (requires conversation_states table — see sql/indexes.sql)
    # ------------------------------------------------------------------

    async def save_conversation_state(self, room_id: str, state: Dict) -> None:
        import json

        def _sync():
            return (
                self.client.table("conversation_states")
                .upsert({
                    "tenant_id": self.tenant_id,
                    "livekit_room_id": room_id,
                    "state": json.dumps(state),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="tenant_id,livekit_room_id")
                .execute()
            )

        try:
            await asyncio.to_thread(_sync)
        except Exception as e:
            logger.warning("Could not save conversation state: %s", e)

    async def load_conversation_state(self, room_id: str) -> Optional[Dict]:
        import json

        def _sync():
            return (
                self.client.table("conversation_states")
                .select("state")
                .eq("tenant_id", self.tenant_id)
                .eq("livekit_room_id", room_id)
                .limit(1)
                .execute()
            )

        try:
            resp = await asyncio.to_thread(_sync)
            if resp.data:
                return json.loads(resp.data[0]["state"])
        except Exception as e:
            logger.warning("Could not load conversation state: %s", e)
        return None

    async def clear_conversation_state(self, room_id: str) -> None:
        def _sync():
            return (
                self.client.table("conversation_states")
                .delete()
                .eq("tenant_id", self.tenant_id)
                .eq("livekit_room_id", room_id)
                .execute()
            )

        try:
            await asyncio.to_thread(_sync)
        except Exception as e:
            logger.warning("Could not clear conversation state: %s", e)
