"""
Google Calendar integration for Maya voice receptionist.
Handles availability checks and booking event management.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
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


def _load_credentials(token_file: str) -> Optional[Credentials]:
    if not os.path.exists(token_file):
        return None
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return creds if creds and creds.valid else None


class GoogleCalendarManager:
    """Manages Google Calendar events for appointment booking."""

    def __init__(self, calendar_id: str = "primary", token_file: str = "google_token.json"):
        self.calendar_id = calendar_id
        self.token_file = token_file
        self._service = None

    def _get_service(self):
        if self._service:
            return self._service
        creds = _load_credentials(self.token_file)
        if not creds:
            raise RuntimeError(
                f"Google Calendar not authorised. Run setup_google_auth.py first. "
                f"Token file not found: {self.token_file}"
            )
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _to_dt(self, date_str: str, time_str: str) -> datetime:
        """Convert YYYY-MM-DD + HH:MM to a timezone-aware datetime in MYT."""
        naive = datetime.strptime(f"{date_str}T{time_str}", "%Y-%m-%dT%H:%M")
        return naive.replace(tzinfo=MYT)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def _check_slot_sync(self, date_str: str, time_str: str) -> bool:
        """Returns True if the slot is free (no overlapping events)."""
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
        """Return list of free HH:MM slots for a given date."""
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

        # Build list of candidate slots
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
            return True  # Fail open — let Supabase double-booking guard catch it

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
        self,
        name: str,
        phone: str,
        date_str: str,
        time_str: str,
        service_type: str,
        booking_ref: str,
    ) -> Optional[str]:
        """Create calendar event, return event ID."""
        cal_service = self._get_service()
        start = self._to_dt(date_str, time_str)
        end = start + timedelta(minutes=SLOT_DURATION_MINUTES)

        event = {
            "summary": f"{service_type} — {name}",
            "description": f"Customer: {name}\nPhone: {phone}\nBooking ref: {booking_ref}\nBooked via Maya Voice AI",
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

    def _update_event_sync(
        self, event_id: str, new_date_str: str, new_time_str: str
    ) -> bool:
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
