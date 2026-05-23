"""
High-level booking helpers for Maya voice receptionist.
Supabase = source of truth for contacts/bookings/sessions.
Google Calendar = synced automatically when google_token.json exists.
"""

import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from config import Config
from database import BookingDatabase
from google_calendar import GoogleCalendarManager

logger = logging.getLogger(__name__)
config = Config()

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"^(\+?60|0)[0-9]{8,10}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def validate_phone(phone: str) -> tuple[bool, str]:
    """Return (valid, cleaned_phone). Malaysian format: +601X or 01X."""
    cleaned = re.sub(r"[\s\-()]", "", phone)
    if not _PHONE_RE.match(cleaned):
        return False, cleaned
    return True, cleaned


def validate_date(date: str) -> tuple[bool, str]:
    """Return (valid, error_message). Must be YYYY-MM-DD, future, max 90 days."""
    if not _DATE_RE.match(date):
        return False, "Date must be in YYYY-MM-DD format."
    try:
        parsed = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return False, "Invalid date value."
    today = datetime.now().date()
    if parsed < today:
        return False, "Appointment date must be in the future."
    if (parsed - today).days > 90:
        return False, "Appointments can only be booked up to 90 days in advance."
    return True, ""


def validate_time(time: str) -> tuple[bool, str]:
    if not _TIME_RE.match(time):
        return False, "Time must be in HH:MM format."
    return True, ""


def sanitize_name(name: str) -> str:
    """Strip control chars, limit length, allow letters/spaces/hyphens/apostrophes."""
    # Normalize unicode and remove control characters
    normalized = unicodedata.normalize("NFC", name)
    cleaned = re.sub(r"[^\w\s\-'./]", "", normalized, flags=re.UNICODE)
    return cleaned.strip()[:100]


# ---------------------------------------------------------------------------
# Rate limiter — max 3 booking attempts per phone per hour (in-memory)
# ---------------------------------------------------------------------------

_rate_store: dict[str, list[datetime]] = defaultdict(list)
_RATE_LIMIT = 3
_RATE_WINDOW = timedelta(hours=1)


def check_rate_limit(phone: str) -> tuple[bool, str]:
    """Return (allowed, message). Blocks after 3 attempts/hour per phone."""
    now = datetime.now()
    cutoff = now - _RATE_WINDOW
    attempts = [t for t in _rate_store[phone] if t > cutoff]
    _rate_store[phone] = attempts
    if len(attempts) >= _RATE_LIMIT:
        return False, (
            "Too many booking attempts for this number. "
            "Please try again in an hour or call us directly."
        )
    _rate_store[phone].append(now)
    return True, ""

# ── FAQ knowledge base ────────────────────────────────────────────────────────

_FAQ: dict[str, str] = {
    "hours": (
        f"We are open {config.business_hours_start} to {config.business_hours_end}, "
        "Monday to Saturday. We are closed on Sundays and public holidays."
    ),
    "location": (
        config.business_address
        if config.business_address
        else f"Please call us at {config.business_phone} for our address details."
    ),
    "payment": (
        "We accept cash, credit/debit cards, and e-wallets such as Touch 'n Go, Boost, and GrabPay. "
        "Insurance cards are also welcome — please bring your card on the day."
    ),
    "parking": (
        "Free parking is available in our building's car park. Street parking is also available nearby."
    ),
    "appointment_duration": (
        "A standard consultation is about 30 minutes. "
        "Specialist appointments or procedures may take longer — we will advise you when booking."
    ),
    "walk_in": (
        "Walk-ins are welcome but subject to availability. "
        "We recommend booking in advance to secure your preferred time slot."
    ),
    "cancel_policy": (
        "You may cancel or reschedule up to 2 hours before your appointment at no charge. "
        "Late cancellations may incur a small administrative fee."
    ),
    "insurance": (
        "We work with most major panel insurance providers. "
        "Please inform us of your insurance when booking so we can prepare the paperwork."
    ),
    "doctor": (
        f"Our clinic is managed by qualified healthcare professionals. "
        f"For specific doctor enquiries please call {config.business_phone or 'our front desk'}."
    ),
    "services": (
        "We offer general consultation, health screenings, vaccinations, minor procedures, "
        "and follow-up care. Specialist referrals are available when needed."
    ),
}

_FAQ_CACHE: dict[str, tuple[str, float]] = {}   # question → (answer, expiry_timestamp)
_FAQ_TTL = 3600.0  # 1 hour

_FAQ_KEYWORDS: dict[str, str] = {
    "hour": "hours", "open": "hours", "close": "hours", "time": "hours", "when": "hours",
    "where": "location", "address": "location", "location": "location", "direction": "location",
    "pay": "payment", "payment": "payment", "card": "payment", "cash": "payment",
    "ewallet": "payment", "tng": "payment", "boost": "payment", "grab": "payment",
    "park": "parking", "parking": "parking",
    "how long": "appointment_duration", "duration": "appointment_duration", "long": "appointment_duration",
    "walk": "walk_in", "walkin": "walk_in", "drop": "walk_in",
    "cancel": "cancel_policy", "reschedule": "cancel_policy", "policy": "cancel_policy",
    "insurance": "insurance", "panel": "insurance", "medcard": "insurance",
    "doctor": "doctor", "dr": "doctor", "specialist": "doctor",
    "service": "services", "treatment": "services", "offer": "services",
}


def answer_faq(question: str) -> Optional[str]:
    """Return FAQ answer if we have a match, else None. Cached for 1 hour."""
    import time
    q = question.lower().strip()
    cached = _FAQ_CACHE.get(q)
    if cached and cached[1] > time.monotonic():
        return cached[0]

    answer = None
    for keyword, topic in _FAQ_KEYWORDS.items():
        if keyword in q:
            answer = _FAQ.get(topic)
            break

    if answer:
        _FAQ_CACHE[q] = (answer, time.monotonic() + _FAQ_TTL)
    return answer


# ── Booking manager ────────────────────────────────────────────────────────────

def _gcal_available() -> bool:
    return os.path.exists(config.google_token_file)


class BookingManager:
    """High-level booking helpers called by agent function tools."""

    def __init__(self):
        self.db = BookingDatabase()
        self._gcal: Optional[GoogleCalendarManager] = (
            GoogleCalendarManager(
                calendar_id=config.google_calendar_id,
                token_file=config.google_token_file,
            )
            if _gcal_available()
            else None
        )
        if self._gcal:
            logger.info("Google Calendar integration active (calendar: %s)", config.google_calendar_id)
        else:
            logger.info("Google Calendar not configured — using availability_slots table only")

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    async def get_slots(self, date: str) -> str:
        if self._gcal:
            free = await self._gcal.get_free_slots(date)
            if not free:
                return f"no_slots|{date}"
            return f"slots|{date}|{','.join(free)}"

        slots = await self.db.get_available_slots(date)
        if not slots:
            return f"no_slots|{date}"
        times = ",".join(s["slot_time"][:5] for s in slots)
        return f"slots|{date}|{times}"

    async def get_next_available(self, days_to_check: int = 7) -> str:
        """Return the first few dates that have open slots, up to days_to_check days ahead."""
        today = datetime.now().date()
        found = []
        for i in range(1, days_to_check + 1):
            check_date = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            result = await self.get_slots(check_date)
            if result.startswith("slots|"):
                _, date_str, times = result.split("|", 2)
                found.append(f"{date_str}: {times}")
                if len(found) >= 3:
                    break
        if not found:
            return "no_upcoming|none"
        return "upcoming|" + ";".join(found)

    # ------------------------------------------------------------------
    # Booking
    # ------------------------------------------------------------------

    async def book(
        self,
        phone: str,
        name: str,
        date: str,
        time: str,
        service: str,
        language: str = "en",
        call_log_id: Optional[str] = None,
    ) -> str:
        # ── Input validation ──────────────────────────────────────────────
        valid_phone, phone = validate_phone(phone)
        if not valid_phone:
            return "That phone number doesn't look right. Could you repeat it with the country code? E.g. 012-345-6789."

        valid_date, date_err = validate_date(date)
        if not valid_date:
            return f"I can't book that date — {date_err}"

        valid_time, time_err = validate_time(time)
        if not valid_time:
            return f"That time doesn't look right — {time_err}"

        name = sanitize_name(name)
        if not name:
            return "I didn't catch the name correctly. Could you repeat it for me?"

        allowed, rate_msg = check_rate_limit(phone)
        if not allowed:
            return rate_msg

        # ── Double-booking guard ──────────────────────────────────────────
        if self._gcal:
            is_free = await self._gcal.check_availability(date, time)
        else:
            is_free = await self.db.check_availability(date, time)

        if not is_free:
            return (
                f"I'm sorry, {date} at {time} is no longer available. "
                "Let me check what other slots are free for you."
            )

        # ── Supabase booking ──────────────────────────────────────────────
        contact = await self.db.find_or_create_contact(phone, name, language)
        scheduled_at = f"{date}T{time}:00+08:00"
        result = await self.db.create_booking(
            contact_id=contact["id"],
            scheduled_at=scheduled_at,
            service_type=service,
            call_log_id=call_log_id,
        )
        if not result:
            return "I'm sorry, I wasn't able to confirm the booking. Please try again or call us directly."

        ref = result["id"][:8].upper()

        # ── Google Calendar sync ──────────────────────────────────────────
        gcal_event_id: Optional[str] = None
        if self._gcal:
            gcal_event_id = await self._gcal.create_event(
                name=name, phone=phone, date_str=date, time_str=time,
                service_type=service, booking_ref=ref,
            )
            if gcal_event_id:
                # Store event ID for future reschedule/cancel
                await self.db.update_booking_gcal_event(result["id"], gcal_event_id)

        return (
            f"Confirmed! Your {service} appointment is on {date} at {time}. "
            f"Your booking reference is {ref}. "
            "We will see you then — please arrive 5 minutes early."
        )

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    async def cancel(self, phone: str, name: Optional[str] = None) -> str:
        booking = await self.db.find_booking(phone, name)
        if not booking:
            return "I could not find an active booking for that phone number. Could you double-check the number?"

        success = await self.db.cancel_booking(booking["id"])
        if not success:
            return "I wasn't able to cancel the booking right now. Please call us directly to cancel."

        dt = booking["scheduled_at"][:16].replace("T", " ")

        # ── Google Calendar sync ──────────────────────────────────────────
        gcal_id = booking.get("calendar_event_id")
        if self._gcal and gcal_id:
            await self._gcal.cancel_event(gcal_id)

        return f"Done — your appointment on {dt} has been cancelled. If you'd like to rebook, just let me know."

    # ------------------------------------------------------------------
    # Reschedule
    # ------------------------------------------------------------------

    async def reschedule(
        self,
        phone: str,
        new_date: str,
        new_time: str,
        name: Optional[str] = None,
    ) -> str:
        booking = await self.db.find_booking(phone, name)
        if not booking:
            return "I could not find an active booking for that number. Could you double-check?"

        # ── Double-booking guard ──────────────────────────────────────────
        if self._gcal:
            is_free = await self._gcal.check_availability(new_date, new_time)
        else:
            is_free = await self.db.check_availability(new_date, new_time)

        if not is_free:
            return (
                f"{new_date} at {new_time} is already taken. "
                "Shall I check other available slots for you?"
            )

        success = await self.db.reschedule_booking(booking["id"], new_date, new_time)
        if not success:
            return "I wasn't able to reschedule. Please call us directly."

        # ── Google Calendar sync ──────────────────────────────────────────
        gcal_id = booking.get("calendar_event_id")
        if self._gcal and gcal_id:
            await self._gcal.update_event(gcal_id, new_date, new_time)

        return (
            f"Your appointment has been moved to {new_date} at {new_time}. "
            "Your booking reference stays the same."
        )

    # ------------------------------------------------------------------
    # FAQ
    # ------------------------------------------------------------------

    async def get_faq_answer(self, question: str) -> str:
        answer = answer_faq(question)
        if answer:
            return answer
        return (
            "I'm not sure about that — let me connect you to our staff who can help you better."
        )
