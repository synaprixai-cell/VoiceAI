"""
Pytest configuration and shared fixtures for Maya tests.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def tomorrow_str() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Booking manager mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_booking_manager():
    bm = MagicMock()
    bm.get_slots = AsyncMock(
        return_value="Available slots: 10:00, 11:00, 14:00, 15:00"
    )
    bm.book = AsyncMock(
        return_value="Booking confirmed! Reference: BK-001. "
                     "Ahmad bin Zainal, General Consultation on "
                     f"{tomorrow_str()} at 10:00."
    )
    bm.cancel = AsyncMock(
        return_value="Booking cancelled successfully."
    )
    bm.reschedule = AsyncMock(
        return_value=f"Appointment rescheduled to {tomorrow_str()} at 14:00."
    )
    bm.get_faq_answer = AsyncMock(
        return_value="Business hours are Monday to Friday, 9am to 6pm MYT."
    )
    return bm


# ---------------------------------------------------------------------------
# Database mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.create_voice_session = AsyncMock(return_value={"id": "session-test-001"})
    db.end_voice_session = AsyncMock(return_value=None)
    db.find_booking = AsyncMock(
        return_value={
            "id": "booking-001",
            "scheduled_at": f"{tomorrow_str()}T10:00:00+08:00",
            "service_type": "General Consultation",
            "status": "confirmed",
        }
    )
    return db


# ---------------------------------------------------------------------------
# Language handler fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def language_handler():
    from language_handler import LanguageHandler
    return LanguageHandler()
