"""
Unit tests for booking_manager validation helpers and FAQ lookup.
These tests have no external dependencies — no DB, no network, no config.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from booking_manager import (
    validate_phone,
    validate_date,
    validate_time,
    sanitize_name,
    answer_faq,
    _FAQ_CACHE,
)


# ---------------------------------------------------------------------------
# validate_phone
# ---------------------------------------------------------------------------

class TestValidatePhone:
    def test_valid_my_011(self):
        ok, cleaned = validate_phone("011-23456789")
        assert ok
        assert cleaned == "01123456789"

    def test_valid_my_012(self):
        ok, cleaned = validate_phone("012 345 6789")
        assert ok
        assert cleaned == "0123456789"

    def test_valid_with_country_code(self):
        ok, cleaned = validate_phone("+60123456789")
        assert ok
        assert cleaned == "+60123456789"

    def test_valid_6012(self):
        ok, cleaned = validate_phone("60123456789")
        assert ok

    def test_invalid_too_short(self):
        ok, _ = validate_phone("0123")
        assert not ok

    def test_invalid_letters(self):
        ok, _ = validate_phone("abc-defghij")
        assert not ok

    def test_invalid_empty(self):
        ok, _ = validate_phone("")
        assert not ok

    def test_strips_spaces_and_dashes(self):
        ok, cleaned = validate_phone("012-345 6789")
        assert ok
        assert " " not in cleaned
        assert "-" not in cleaned


# ---------------------------------------------------------------------------
# validate_date
# ---------------------------------------------------------------------------

class TestValidateDate:
    def _future(self, days=1):
        return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

    def test_valid_tomorrow(self):
        ok, err = validate_date(self._future(1))
        assert ok
        assert err == ""

    def test_valid_30_days_ahead(self):
        ok, _ = validate_date(self._future(30))
        assert ok

    def test_invalid_past(self):
        past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        ok, err = validate_date(past)
        assert not ok
        assert "future" in err.lower()

    def test_valid_today(self):
        # Same-day bookings are allowed (parsed < today check, not <=)
        today = datetime.now().strftime("%Y-%m-%d")
        ok, _ = validate_date(today)
        assert ok

    def test_invalid_too_far_ahead(self):
        ok, err = validate_date(self._future(91))
        assert not ok
        assert "90" in err

    def test_invalid_format(self):
        ok, err = validate_date("23/05/2026")
        assert not ok
        assert "YYYY-MM-DD" in err

    def test_invalid_nonsense(self):
        ok, _ = validate_date("not-a-date")
        assert not ok

    def test_invalid_bad_value(self):
        ok, _ = validate_date("2026-13-99")
        assert not ok


# ---------------------------------------------------------------------------
# validate_time
# ---------------------------------------------------------------------------

class TestValidateTime:
    def test_valid_09_00(self):
        ok, err = validate_time("09:00")
        assert ok
        assert err == ""

    def test_valid_14_30(self):
        ok, err = validate_time("14:30")
        assert ok

    def test_invalid_no_colon(self):
        ok, err = validate_time("0900")
        assert not ok

    def test_invalid_single_digit(self):
        ok, _ = validate_time("9:00")
        assert not ok

    def test_invalid_empty(self):
        ok, _ = validate_time("")
        assert not ok

    def test_invalid_with_seconds(self):
        ok, _ = validate_time("09:00:00")
        assert not ok


# ---------------------------------------------------------------------------
# sanitize_name
# ---------------------------------------------------------------------------

class TestSanitizeName:
    def test_normal_name(self):
        assert sanitize_name("Ahmad bin Zainal") == "Ahmad bin Zainal"

    def test_name_with_apostrophe(self):
        assert "O'Brien" == sanitize_name("O'Brien")

    def test_strips_control_chars(self):
        result = sanitize_name("Ali\x00\x01Hassan")
        assert "\x00" not in result
        assert "\x01" not in result

    def test_strips_html(self):
        result = sanitize_name("<script>alert(1)</script>")
        assert "<" not in result
        assert ">" not in result

    def test_length_limit(self):
        long_name = "A" * 200
        assert len(sanitize_name(long_name)) <= 100

    def test_strips_whitespace(self):
        assert sanitize_name("  Ali  ") == "Ali"

    def test_empty_string(self):
        assert sanitize_name("") == ""

    def test_unicode_malay(self):
        result = sanitize_name("Nurul Ain binti Aziz")
        assert "Nurul" in result

    def test_unicode_chinese(self):
        result = sanitize_name("李明")
        assert len(result) > 0


# ---------------------------------------------------------------------------
# answer_faq
# ---------------------------------------------------------------------------

class TestAnswerFaq:
    def setup_method(self):
        _FAQ_CACHE.clear()

    def test_hours_keyword(self):
        result = answer_faq("what are your opening hours?")
        assert result is not None
        assert "open" in result.lower() or "monday" in result.lower()

    def test_location_keyword(self):
        result = answer_faq("where are you located?")
        assert result is not None

    def test_payment_keyword(self):
        result = answer_faq("what payment methods do you accept?")
        assert result is not None
        assert any(w in result.lower() for w in ["cash", "card", "ewallet", "e-wallet"])

    def test_parking_keyword(self):
        result = answer_faq("is there parking available?")
        assert result is not None
        assert "park" in result.lower()

    def test_cancel_policy_keyword(self):
        result = answer_faq("can I cancel my appointment?")
        assert result is not None

    def test_no_match_returns_none(self):
        result = answer_faq("asdfghjkl random gibberish zzz")
        assert result is None

    def test_cache_hit(self):
        q = "what are the hours?"
        first = answer_faq(q)
        second = answer_faq(q)
        assert first == second

    def test_case_insensitive(self):
        lower = answer_faq("opening hours")
        upper = answer_faq("OPENING HOURS")
        assert lower == upper

    def test_services_keyword(self):
        result = answer_faq("what services do you offer?")
        assert result is not None

    def test_insurance_keyword(self):
        result = answer_faq("do you accept insurance?")
        assert result is not None
