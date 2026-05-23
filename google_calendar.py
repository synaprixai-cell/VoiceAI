"""
Google Calendar integration for Maya voice receptionist.
Credentials are loaded from Supabase tenant_settings (shared with WhatsApp agent)
so both agents always sync to the same calendar.
Falls back to google_token.json for local dev.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
MY_TIMEZONE = "Asia/Kuala_Lumpur"
MYT = ZoneInfo(MY_TIMEZONE)
SLOT_DURATION_MINUTES = 30


# ---------------------------------------------------------------------------
# Credential loading — DB first, file fallback
# ---------------------------------------------------------------------------

def _load_credentials_from_db(tenant_id: str) -> Tuple[Optional[Credentials], Optional[str]]:
    """
    Load Google OAuth credentials + calendar_id from tenant_settings.
    Returns (credentials, calendar_id). Both may be None if not configured.
    Automatically refreshes the access token and writes it back to the DB.
    """
    try:
        from supabase import create_client
        from config import Config
        config = Config()

        client = create_client(config.supabase_url, config.supabase_key)
        result = (
            client.table("tenant_settings")
            .select("google_calendar_token,google_calendar_refresh,google_calendar_id")
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if not result.data:
            return None, None

        refresh_token: Optional[str] = result.data.get("google_calendar_refresh")
        access_token: Optional[str] = result.data.get("google_calendar_token")
        calendar_id: str = result.data.get("google_calendar_id") or "primary"

        if not refresh_token and not access_token:
            return None, None

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            scopes=SCOPES,
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Write refreshed access token back so WhatsApp agent also benefits
            try:
                client.table("tenant_settings").update(
                    {"google_calendar_token": creds.token}
                ).eq("tenant_id", tenant_id).execute()
            except Exception as e:
                logger.warning("Could not write refreshed token to DB: %s", e)

        return (creds if creds.valid else None), calendar_id

    except Exception as e:
        logger.warning("Could not load Google Calendar creds from DB: %s", e)
        return None, None


def _load_credentials_from_file(token_file: str) -> Optional[Credentials]:
    """Load Google OAuth credentials from a local JSON file (local dev only)."""
    if not os.path.exists(token_file):
        return None
    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        return creds if (creds and creds.valid) else None
    except Exception as e:
        logger.warning("Could not load Google Calendar creds from file: %s", e)
        return None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class GoogleCalendarManager:
    """
    Manages Google Calendar events for appointment booking.
    Reads OAuth credentials from Supabase tenant_settings so both the
    WhatsApp agent and voice agent share the same authorised calendar.
    """

    def __init__(
        self,
        calendar_id: str = "primary",
        token_file: str = "google_token.json",
        tenant_id: Optional[str] = None,
    ):
        self.calendar_id = calendar_id
        self.token_file = token_file
        self.tenant_id = tenant_id
        self._service = None

    def _get_service(self):
        if self._service:
            return self._service

        creds: Optional[Credentials] = None

        # 1. Try DB credentials first (production — shared with WhatsApp agent)
        if self.tenant_id:
            db_creds, db_calendar_id = _load_credentials_from_db(self.tenant_id)
            if db_creds:
                creds = db_creds
                # Use calendar_id from DB if not overridden
                if db_calendar_id and self.calendar_id == "primary":
                    self.calendar_id = db_calendar_id
                logger.info("Google Calendar: using credentials from tenant_settings (tenant=%s)", self.tenant_id)

        # 2. Fall back to local file (local dev with google_token.json)
        if not creds:
            creds = _load_credentials_from_file(self.token_file)
            if creds:
                logger.info("Google Calendar: using credentials from %s", self.token_file)

        if not creds:
            raise RuntimeError(
                "Google Calendar not authorised. Either:\n"
                "  1. Connect Google Calendar in the dashboard settings, or\n"
                f"  2. Run setup_google_auth.py locally to create {self.token_file}"
            )

        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _to_dt(self, date_str: str, time_str: str) -> datetime:
        naive = datetime.strptime(f"{date_str}T{time_str}", "%Y-%m-%dT%H:%M")
        return naive.replace(tzinfo=MYT)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def _check_slot_sync(self, date_str: str, time_str: str) -> bool:
        service = self._get_service()
        start = self._to_dt(date_str, time_str)
        end = start + timedelta(minutes=SLOT_DURATION_MINUTES)
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": self.calendar_id}],
            "timeZone": MY_TIMEZONE,
        }
        result = service.freebusy().query(body=body).execute()
        busy = result["calendars"].get(self.calendar_id, {}).get("busy", [])
        return len(busy) == 0

    def _get_free_slots_sync(self, date_str: str, start_hour: int = 9, end_hour: int = 18) -> list[str]:
        service = self._get_service()
        day_start = self._to_dt(date_str, f"{start_hour:02d}:00")
        day_end = self._to_dt(date_str, f"{end_hour:02d}:00")
        body = {
            "timeMin": day_start.isoformat(),
            "timeMax": day_end.isoformat(),
            "items": [{"id": self.calendar_id}],
            "timeZone": MY_TIMEZONE,
        }
        result = service.freebusy().query(body=body).execute()
        busy_blocks = result["calendars"].get(self.calendar_id, {}).get("busy", [])
        busy_intervals = [
            (
                datetime.fromisoformat(b["start"]).astimezone(MYT),
                datetime.fromisoformat(b["end"]).astimezone(MYT),
            )
            for b in busy_blocks
        ]
        free = []
        current = day_start
        while current + timedelta(minutes=SLOT_DURATION_MINUTES) <= day_end:
            slot_end = current + timedelta(minutes=SLOT_DURATION_MINUTES)
            overlap = any(
                not (slot_end <= b_start or current >= b_end)
                for b_start, b_end in busy_intervals
            )
            if not overlap:
                free.append(current.strftime("%H:%M"))
            current += timedelta(minutes=SLOT_DURATION_MINUTES)
        return free

    async def check_availability(self, date_str: str, time_str: str) -> bool:
        try:
            return await asyncio.to_thread(self._check_slot_sync, date_str, time_str)
        except Exception as e:
            logger.error("Google Calendar availability check failed: %s", e)
            return True  # Fail open — Supabase double-booking guard catches duplicates

    async def get_free_slots(self, date_str: str) -> list[str]:
        try:
            return await asyncio.to_thread(self._get_free_slots_sync, date_str)
        except Exception as e:
            logger.error("Google Calendar get_free_slots failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Event CRUD
    # ------------------------------------------------------------------

    def _create_event_sync(
        self, name: str, phone: str, date_str: str, time_str: str,
        service_type: str, booking_ref: str,
    ) -> Optional[str]:
        cal_service = self._get_service()
        start = self._to_dt(date_str, time_str)
        end = start + timedelta(minutes=SLOT_DURATION_MINUTES)
        event = {
            "summary": f"{service_type} — {name}",
            "description": (
                f"Customer: {name}\nPhone: {phone}\n"
                f"Booking ref: {booking_ref}\nBooked via Maya Voice AI"
            ),
            "start": {"dateTime": start.isoformat(), "timeZone": MY_TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": MY_TIMEZONE},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 60},
                    {"method": "popup", "minutes": 15},
                ],
            },
        }
        result = cal_service.events().insert(calendarId=self.calendar_id, body=event).execute()
        return result.get("id")

    def _update_event_sync(self, event_id: str, new_date_str: str, new_time_str: str) -> bool:
        cal_service = self._get_service()
        event = cal_service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
        start = self._to_dt(new_date_str, new_time_str)
        end = start + timedelta(minutes=SLOT_DURATION_MINUTES)
        event["start"] = {"dateTime": start.isoformat(), "timeZone": MY_TIMEZONE}
        event["end"] = {"dateTime": end.isoformat(), "timeZone": MY_TIMEZONE}
        cal_service.events().update(calendarId=self.calendar_id, eventId=event_id, body=event).execute()
        return True

    def _cancel_event_sync(self, event_id: str) -> bool:
        cal_service = self._get_service()
        cal_service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
        return True

    async def create_event(
        self, name: str, phone: str, date_str: str, time_str: str,
        service_type: str, booking_ref: str,
    ) -> Optional[str]:
        try:
            return await asyncio.to_thread(
                self._create_event_sync, name, phone, date_str, time_str, service_type, booking_ref
            )
        except HttpError as e:
            logger.error("Google Calendar create_event failed: %s", e)
            return None

    async def update_event(self, event_id: str, new_date_str: str, new_time_str: str) -> bool:
        try:
            return await asyncio.to_thread(self._update_event_sync, event_id, new_date_str, new_time_str)
        except HttpError as e:
            logger.error("Google Calendar update_event failed: %s", e)
            return False

    async def cancel_event(self, event_id: str) -> bool:
        try:
            return await asyncio.to_thread(self._cancel_event_sync, event_id)
        except HttpError as e:
            logger.error("Google Calendar cancel_event failed: %s", e)
            return False
