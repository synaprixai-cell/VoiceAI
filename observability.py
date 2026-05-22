"""
Structured logging and metrics for Maya.
Lightweight — no external tracing service required.
In production, swap the logging handlers for your OTLP/Datadog/Grafana sink.
"""

import logging
import re
import time
from collections import defaultdict

# ---------------------------------------------------------------------------
# PII scrubbing filter — strips phone numbers from all log output
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"(\+?60|0)[0-9]{8,10}")
_NRIC_RE  = re.compile(r"\b\d{6}-?\d{2}-?\d{4}\b")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class PIIFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        record.args = _scrub_args(record.args)
        return True


def _scrub(text: str) -> str:
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _NRIC_RE.sub("[NRIC]", text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    return text


def _scrub_args(args):
    if args is None:
        return args
    if isinstance(args, tuple):
        return tuple(_scrub(str(a)) if isinstance(a, str) else a for a in args)
    if isinstance(args, dict):
        return {k: (_scrub(str(v)) if isinstance(v, str) else v) for k, v in args.items()}
    return args
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Structured logger — injects room_id and job_id into every record
# ---------------------------------------------------------------------------

class ContextFilter(logging.Filter):
    """Adds room_id and job_id fields so every log line is identifiable."""

    def __init__(self):
        super().__init__()
        self._room_id: str = "-"
        self._job_id: str = "-"

    def set_context(self, room_id: str = "-", job_id: str = "-") -> None:
        self._room_id = room_id
        self._job_id = job_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.room_id = self._room_id
        record.job_id = self._job_id
        return True


_ctx_filter = ContextFilter()


_pii_filter = PIIFilter()


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure structured logging for the entire process.
    Format: timestamp | level | [room=X job=Y] | logger | message
    PII (phone numbers, NRIC, email) is scrubbed from all output.
    """
    fmt = "%(asctime)s | %(levelname)-8s | [room=%(room_id)s job=%(job_id)s] | %(name)s | %(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    handler.addFilter(_ctx_filter)
    handler.addFilter(_pii_filter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def set_log_context(room_id: str = "-", job_id: str = "-") -> None:
    _ctx_filter.set_context(room_id=room_id, job_id=job_id)


# ---------------------------------------------------------------------------
# Lightweight in-process metrics
# ---------------------------------------------------------------------------

@dataclass
class _Metrics:
    sessions_started: int = 0
    sessions_ended: int = 0
    bookings_attempted: int = 0
    bookings_confirmed: int = 0
    bookings_failed: int = 0
    cancellations: int = 0
    reschedules: int = 0
    faq_queries: int = 0
    human_transfers: int = 0
    stt_fallbacks: int = 0
    tts_fallbacks: int = 0
    llm_fallbacks: int = 0
    language_switches: dict = field(default_factory=lambda: defaultdict(int))
    latencies_ms: dict = field(default_factory=lambda: defaultdict(list))

    def record_latency(self, operation: str, ms: float) -> None:
        self.latencies_ms[operation].append(ms)

    def p95(self, operation: str) -> Optional[float]:
        values = sorted(self.latencies_ms.get(operation, []))
        if not values:
            return None
        idx = int(len(values) * 0.95)
        return values[min(idx, len(values) - 1)]

    def summary(self) -> dict:
        return {
            "sessions": {"started": self.sessions_started, "ended": self.sessions_ended},
            "bookings": {
                "attempted": self.bookings_attempted,
                "confirmed": self.bookings_confirmed,
                "failed": self.bookings_failed,
            },
            "actions": {
                "cancellations": self.cancellations,
                "reschedules": self.reschedules,
                "faq_queries": self.faq_queries,
                "human_transfers": self.human_transfers,
            },
            "fallbacks": {
                "stt": self.stt_fallbacks,
                "tts": self.tts_fallbacks,
                "llm": self.llm_fallbacks,
            },
            "language_switches": dict(self.language_switches),
            "p95_latency_ms": {
                op: round(self.p95(op) or 0, 1)
                for op in self.latencies_ms
            },
        }


metrics = _Metrics()


# ---------------------------------------------------------------------------
# Timing context manager
# ---------------------------------------------------------------------------

@contextmanager
def timed(operation: str):
    """Usage: async with timed("booking"): ..."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        metrics.record_latency(operation, elapsed_ms)


# ---------------------------------------------------------------------------
# Convenience log helpers used by agent.py / booking_manager.py
# ---------------------------------------------------------------------------

_logger = logging.getLogger("maya.observability")


def log_session_start(room_id: str, job_id: str = "-") -> None:
    set_log_context(room_id=room_id, job_id=job_id)
    metrics.sessions_started += 1
    _logger.info("Session started | room=%s", room_id)


def log_session_end(room_id: str, duration_sec: float = 0) -> None:
    metrics.sessions_ended += 1
    _logger.info("Session ended | room=%s | duration=%.1fs", room_id, duration_sec)


def log_booking_attempt(name: str, date: str, service: str) -> None:
    metrics.bookings_attempted += 1
    _logger.info("Booking attempt | name=%s | date=%s | service=%s", name, date, service)


def log_booking_result(success: bool, reference: str = "") -> None:
    if success:
        metrics.bookings_confirmed += 1
        _logger.info("Booking confirmed | ref=%s", reference)
    else:
        metrics.bookings_failed += 1
        _logger.warning("Booking failed | ref=%s", reference)


def log_language_switch(from_lang: str, to_lang: str) -> None:
    metrics.language_switches[f"{from_lang}→{to_lang}"] += 1
    _logger.info("Language switch | %s → %s", from_lang, to_lang)


def log_fallback(component: str, primary: str, fallback: str, reason: str) -> None:
    if component == "stt":
        metrics.stt_fallbacks += 1
    elif component == "tts":
        metrics.tts_fallbacks += 1
    elif component == "llm":
        metrics.llm_fallbacks += 1
    _logger.warning(
        "Fallback activated | component=%s | %s → %s | reason=%s",
        component, primary, fallback, reason,
    )


def log_transfer(reason: str) -> None:
    metrics.human_transfers += 1
    _logger.info("Transfer to human | reason=%s", reason)


def print_metrics_summary() -> None:
    import json
    _logger.info("Metrics summary:\n%s", json.dumps(metrics.summary(), indent=2))
