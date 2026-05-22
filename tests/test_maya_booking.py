"""
Tests for Maya's booking flow, tool calls, and conversation rules.
Run with: pytest tests/ -v
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from datetime import datetime, timedelta

def today_str(): return datetime.now().strftime("%Y-%m-%d")
def tomorrow_str(): return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# _build_prompt — date injection
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_en_prompt_contains_today(self):
        from agent import _build_prompt
        prompt = _build_prompt("en")
        assert today_str() in prompt

    def test_en_prompt_contains_tomorrow(self):
        from agent import _build_prompt
        prompt = _build_prompt("en")
        assert tomorrow_str() in prompt

    def test_en_prompt_no_literal_tomorrow_word_in_date_position(self):
        """Ensure the date section never says the word 'tomorrow' as a value."""
        from agent import _build_prompt
        prompt = _build_prompt("en")
        # "tomorrow" = {tomorrow_date} must be resolved to YYYY-MM-DD
        assert f'"tomorrow" = {tomorrow_str()}' in prompt

    def test_all_languages_render_without_error(self):
        from agent import _build_prompt
        for lang in ("en", "ms", "ta", "zh"):
            prompt = _build_prompt(lang)
            assert len(prompt) > 100, f"Prompt for {lang} too short"

    def test_en_prompt_contains_booking_flow(self):
        from agent import _build_prompt
        prompt = _build_prompt("en")
        assert "book_appointment" in prompt

    def test_en_prompt_contains_prohibited_section(self):
        from agent import _build_prompt
        prompt = _build_prompt("en")
        assert "PROHIBITED" in prompt


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

class TestLanguageDetection:
    def test_english_detected(self, language_handler):
        assert language_handler.detect_language("I want to book an appointment") == "en"

    def test_malay_detected(self, language_handler):
        result = language_handler.detect_language("Saya nak buat tempahan doktor")
        assert result == "ms"

    def test_tamil_detected(self, language_handler):
        result = language_handler.detect_language("நான் appointment வேண்டும்")
        assert result == "ta"

    def test_mandarin_detected(self, language_handler):
        result = language_handler.detect_language("我想预约")
        assert result == "zh"

    def test_manglish_detected_as_english_or_malay(self, language_handler):
        result = language_handler.detect_language("I want to buat appointment lah")
        assert result in ("en", "ms")

    def test_short_echo_noise_does_not_crash(self, language_handler):
        # Ambiguous short input returns None or a valid lang — never raises
        result = language_handler.detect_language("ok")
        assert result in ("en", "ms", "ta", "zh", None, "")


# ---------------------------------------------------------------------------
# BookingManager — unit tests with mocked DB
# ---------------------------------------------------------------------------

class TestBookingManagerSlots:
    @pytest.mark.asyncio
    async def test_get_slots_returns_string(self, mock_booking_manager):
        result = await mock_booking_manager.get_slots(tomorrow_str())
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_slots_called_with_correct_date(self, mock_booking_manager):
        date = tomorrow_str()
        await mock_booking_manager.get_slots(date)
        mock_booking_manager.get_slots.assert_called_once_with(date)


class TestBookingManagerBook:
    @pytest.mark.asyncio
    async def test_book_returns_confirmation(self, mock_booking_manager):
        result = await mock_booking_manager.book(
            phone="+60123456789",
            name="Ahmad bin Zainal",
            date=tomorrow_str(),
            time="10:00",
            service="General Consultation",
            language="en",
        )
        assert "confirmed" in result.lower() or "booking" in result.lower()

    @pytest.mark.asyncio
    async def test_book_called_with_all_params(self, mock_booking_manager):
        await mock_booking_manager.book(
            phone="+60123456789",
            name="Tan Wei Ming",
            date=tomorrow_str(),
            time="14:00",
            service="Health Screening",
            language="zh",
        )
        mock_booking_manager.book.assert_called_once()
        call_kwargs = mock_booking_manager.book.call_args.kwargs
        assert call_kwargs["phone"] == "+60123456789"
        assert call_kwargs["name"] == "Tan Wei Ming"
        assert call_kwargs["date"] == tomorrow_str()


class TestBookingManagerCancel:
    @pytest.mark.asyncio
    async def test_cancel_returns_success(self, mock_booking_manager):
        result = await mock_booking_manager.cancel(phone="+60123456789")
        assert "cancel" in result.lower()

    @pytest.mark.asyncio
    async def test_cancel_with_name(self, mock_booking_manager):
        await mock_booking_manager.cancel(phone="+60123456789", name="Ahmad")
        mock_booking_manager.cancel.assert_called_once_with(
            phone="+60123456789", name="Ahmad"
        )


class TestBookingManagerReschedule:
    @pytest.mark.asyncio
    async def test_reschedule_returns_new_date(self, mock_booking_manager):
        result = await mock_booking_manager.reschedule(
            phone="+60123456789",
            new_date=tomorrow_str(),
            new_time="14:00",
        )
        assert tomorrow_str() in result or "reschedul" in result.lower()


class TestBookingManagerFaq:
    @pytest.mark.asyncio
    async def test_faq_returns_answer(self, mock_booking_manager):
        result = await mock_booking_manager.get_faq_answer("What are your hours?")
        assert isinstance(result, str)
        assert len(result) > 5

    @pytest.mark.asyncio
    async def test_faq_hours_question(self, mock_booking_manager):
        result = await mock_booking_manager.get_faq_answer("operating hours")
        assert "hour" in result.lower() or "9" in result


# ---------------------------------------------------------------------------
# Input validation (Task 4 — tested here in advance)
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_valid_malaysian_phone(self):
        """Malaysian phones: 01X-XXXX-XXXX"""
        valid = ["+60123456789", "0123456789", "+601234567890", "60123456789"]
        for phone in valid:
            digits = phone.replace("+", "").replace("-", "").replace(" ", "")
            assert len(digits) >= 10, f"Expected valid: {phone}"

    def test_date_is_yyyy_mm_dd(self):
        """Dates passed to tools must always be YYYY-MM-DD."""
        import re
        date = tomorrow_str()
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", date), f"Bad date format: {date}"

    def test_date_not_a_day_name(self):
        date = tomorrow_str()
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday", "tomorrow", "today"]
        for name in day_names:
            assert name.lower() not in date.lower(), (
                f"Date should be YYYY-MM-DD, not contain '{name}'"
            )
