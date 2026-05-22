"""
Custom LiveKit TTS plugin using Microsoft Edge TTS (edge-tts).
Completely free — no API key required.
Supports all Malaysian languages: en-SG, ms-MY, ta-MY, zh-CN.
"""

import uuid
from dataclasses import dataclass

import edge_tts
from livekit.agents import tts
from livekit.agents.tts import TTSCapabilities, AudioEmitter
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

# Malaysian/regional neural voices — all free via Edge TTS
VOICES = {
    "en": "en-SG-LunaNeural",     # English (Singapore) – closest regional accent to Malaysian English
    "ms": "ms-MY-YasminNeural",   # Malay (Malaysia) – female
    "ta": "ta-MY-KaniNeural",     # Tamil (Malaysia) – female
    "zh": "zh-CN-XiaoxiaoNeural", # Mandarin – female, expressive
}

SAMPLE_RATE = 24_000
NUM_CHANNELS = 1


@dataclass
class EdgeTTSOptions:
    voice: str
    rate: str = "+0%"
    volume: str = "+0%"


class EdgeChunkedStream(tts.ChunkedStream):
    """Streams edge-tts MP3 output directly to LiveKit via AudioEmitter."""

    def __init__(self, *, tts_instance: "EdgeTTS", input_text: str,
                 opts: EdgeTTSOptions, conn_options: APIConnectOptions):
        super().__init__(tts=tts_instance, input_text=input_text, conn_options=conn_options)
        self._opts = opts
        self._request_id = str(uuid.uuid4().hex[:8])

    async def _run(self, output_emitter: AudioEmitter) -> None:
        communicate = edge_tts.Communicate(
            self._input_text,
            self._opts.voice,
            rate=self._opts.rate,
            volume=self._opts.volume,
        )

        output_emitter.initialize(
            request_id=self._request_id,
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            mime_type="audio/mpeg",
        )

        # Stream MP3 chunks directly — AudioEmitter decodes via FFmpeg internally
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                output_emitter.push(chunk["data"])

        output_emitter.flush()


class EdgeTTS(tts.TTS):
    """
    LiveKit TTS plugin backed by Microsoft Edge TTS.
    Free, no API key. Supports en-MY, ms-MY, ta-MY, zh-CN neural voices.
    """

    def __init__(self, *, language: str = "en"):
        super().__init__(
            capabilities=TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._language = language
        self._opts = EdgeTTSOptions(voice=VOICES.get(language, VOICES["en"]))

    def set_language(self, language: str) -> None:
        """Dynamically switch language/voice."""
        self._language = language
        self._opts = EdgeTTSOptions(voice=VOICES.get(language, VOICES["en"]))

    @property
    def current_voice(self) -> str:
        return self._opts.voice

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> EdgeChunkedStream:
        return EdgeChunkedStream(
            tts_instance=self,
            input_text=text,
            opts=self._opts,
            conn_options=conn_options,
        )
