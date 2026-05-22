"""
Language detection for Malaysian multilingual context.
Handles: English, Malay (Bahasa Malaysia), Manglish, Tamil, Mandarin.
"""

import re
from typing import Dict, Optional


class LanguageHandler:
    def __init__(self):
        # High-confidence single-language markers
        self._tamil_re = re.compile(r"[஀-௿]")   # Tamil Unicode block
        self._mandarin_re = re.compile(r"[一-鿿㐀-䶿]")  # CJK

        # Malay keyword patterns (common words + particles)
        self._malay_words = {
            "saya", "nak", "nak", "tak", "ye", "ya", "la", "lah", "kan",
            "boleh", "tolong", "maaf", "terima kasih", "dengan", "untuk",
            "sekarang", "esok", "hari", "masa", "tarikh", "tempahan",
            "buat", "batalkan", "tukar", "semak", "ada", "tidak",
            "awak", "anda", "encik", "puan", "cik", "nombor", "telefon",
            "perkhidmatan", "klinik", "doktor", "ubat",
        }

        # Manglish markers (English mixed with Malay particles/loanwords)
        self._manglish_words = {
            "lah", "leh", "lor", "mah", "wor", "ah", "hor", "nia",
            "aiyah", "aiyoh", "walao", "confirm", "can", "cannot",
            "already", "also", "one", "got", "want",
        }

        self.greetings: Dict[str, str] = {
            "en": "Hello! Welcome to {}. How may I assist you today?",
            "ms": "Selamat datang ke {}! Boleh saya membantu anda?",
            "ta": "வணக்கம்! {} க்கு வரவேற்கிறோம். நான் உங்களுக்கு எப்படி உதவலாம்?",
            "zh": "您好！欢迎来到{}。请问有什么可以帮您？",
        }

        # Edge TTS neural voices — Malaysian/regional
        self.voice_map: Dict[str, str] = {
            "en": "en-SG-LunaNeural",
            "ms": "ms-MY-YasminNeural",
            "ta": "ta-MY-KaniNeural",
            "zh": "zh-CN-XiaoxiaoNeural",
        }

    def detect_language(self, text: str) -> Optional[str]:
        """
        Returns 'en', 'ms', 'ta', or 'zh'.
        Returns None if detection is inconclusive (let Whisper's result stand).
        """
        if not text or len(text.strip()) < 2:
            return None

        # 1. Script-based detection (highest confidence)
        if self._tamil_re.search(text):
            return "ta"
        if self._mandarin_re.search(text):
            return "zh"

        # 2. Token-based detection for Latin-script languages (Malay vs English/Manglish)
        tokens = set(re.sub(r"[^\w\s]", "", text.lower()).split())

        malay_hits = len(tokens & self._malay_words)
        manglish_hits = len(tokens & self._manglish_words)

        # Manglish = English + particles → treat as English for STT/TTS
        if malay_hits >= 2:
            return "ms"
        if manglish_hits >= 1 and malay_hits == 0:
            return "en"  # Manglish → respond in English
        if malay_hits == 1:
            return "ms"  # weak Malay signal still counts

        return None  # fallback: trust Whisper's detected language

    def get_greeting(self, language: str, business_name: str) -> str:
        template = self.greetings.get(language, self.greetings["en"])
        return template.format(business_name)

    def get_voice(self, language: str) -> str:
        return self.voice_map.get(language, self.voice_map["en"])
