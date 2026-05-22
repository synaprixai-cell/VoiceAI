"""
Language-specific tests: prompts, detection, voice routing.
"""

import pytest
from datetime import datetime, timedelta

def today_str(): return datetime.now().strftime("%Y-%m-%d")
def tomorrow_str(): return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


class TestSystemPrompts:
    LANGS = ["en", "ms", "ta", "zh"]

    @pytest.mark.parametrize("lang", LANGS)
    def test_prompt_has_business_name(self, lang):
        from agent import _build_prompt
        prompt = _build_prompt(lang)
        assert "My Clinic" in prompt or "{business_name}" not in prompt

    @pytest.mark.parametrize("lang", LANGS)
    def test_prompt_has_today_date(self, lang):
        from agent import _build_prompt
        prompt = _build_prompt(lang)
        assert today_str() in prompt

    @pytest.mark.parametrize("lang", LANGS)
    def test_prompt_has_tomorrow_date(self, lang):
        from agent import _build_prompt
        prompt = _build_prompt(lang)
        assert tomorrow_str() in prompt

    def test_malay_prompt_has_formal_address(self):
        from agent import _build_prompt
        prompt = _build_prompt("ms")
        assert "Encik" in prompt or "Puan" in prompt

    def test_mandarin_prompt_uses_formal_you(self):
        from agent import _build_prompt
        prompt = _build_prompt("zh")
        assert "您" in prompt

    def test_tamil_prompt_has_formal_address(self):
        from agent import _build_prompt
        prompt = _build_prompt("ta")
        assert "அய்யா" in prompt or "அம்மா" in prompt or "மரியாதை" in prompt

    def test_en_prompt_one_question_per_turn_rule(self):
        from agent import _build_prompt
        prompt = _build_prompt("en")
        assert "ONE question per turn" in prompt or "one step per turn" in prompt.lower()


class TestVoiceIds:
    def test_all_four_voice_ids_defined(self):
        from agent import ELEVENLABS_VOICES
        for lang in ("en", "ms", "zh", "ta"):
            assert lang in ELEVENLABS_VOICES
            assert len(ELEVENLABS_VOICES[lang]) > 10  # valid UUID-like string

    def test_voice_ids_are_unique(self):
        from agent import ELEVENLABS_VOICES
        ids = list(ELEVENLABS_VOICES.values())
        assert len(ids) == len(set(ids)), "Duplicate voice IDs found"


class TestLanguageDetectionEdgeCases:
    def test_mixed_english_malay(self, language_handler):
        text = "boleh tolong I nak book appointment tak"
        result = language_handler.detect_language(text)
        assert result in ("en", "ms")

    def test_empty_string_returns_something(self, language_handler):
        result = language_handler.detect_language("")
        assert result in ("en", "ms", "ta", "zh", None, "")

    def test_tamil_unicode_script(self, language_handler):
        result = language_handler.detect_language("நன்றி")
        assert result == "ta"

    def test_chinese_characters(self, language_handler):
        result = language_handler.detect_language("谢谢你")
        assert result == "zh"

    def test_pure_english_greeting(self, language_handler):
        # Ambiguous English may return en or None (caller falls back to current lang)
        result = language_handler.detect_language("Hello good morning")
        assert result in ("en", None, "")
