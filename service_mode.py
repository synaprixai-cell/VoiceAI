"""
ServiceMode — determines what Maya can do based on which services are reachable.

FULL      : Database + Calendar both up   → full booking flow
DEGRADED  : Database up, Calendar down   → bookings work, no calendar sync
EMERGENCY : Database down                 → transfer all calls to human
"""

import logging
import os
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ServiceMode(Enum):
    FULL = "full"
    DEGRADED = "degraded"
    EMERGENCY = "emergency"


async def check_database(db) -> bool:
    """Ping Supabase with a minimal query."""
    try:
        import asyncio
        def _ping():
            return db.client.table("contacts").select("id").limit(1).execute()
        await asyncio.to_thread(_ping)
        return True
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        return False


async def check_calendar(gcal) -> bool:
    """Check if Google Calendar token is valid."""
    if gcal is None:
        return False
    try:
        creds = gcal._get_credentials()
        return creds is not None and creds.valid
    except Exception:
        return False


async def determine_mode(db, gcal=None) -> ServiceMode:
    db_ok = await check_database(db)
    if not db_ok:
        logger.error("ServiceMode → EMERGENCY (database unreachable)")
        return ServiceMode.EMERGENCY

    cal_ok = await check_calendar(gcal)
    if gcal is not None and not cal_ok:
        logger.warning("ServiceMode → DEGRADED (calendar unreachable, bookings still work)")
        return ServiceMode.DEGRADED

    logger.info("ServiceMode → FULL")
    return ServiceMode.FULL


def mode_notice(mode: ServiceMode, language: str = "en") -> Optional[str]:
    """Return a phrase Maya should say at the start of a degraded/emergency session."""
    if mode == ServiceMode.FULL:
        return None
    notices = {
        ServiceMode.DEGRADED: {
            "en": "Just to let you know, our calendar sync is temporarily delayed — your booking will still be confirmed.",
            "ms": "Sekadar maklum, penyegerakan kalendar kami mengalami kelewatan sementara — tempahan anda tetap disahkan.",
            "ta": "தகவலுக்கு — நமது காலண்டர் ஒத்திசைவு தாமதமாகிறது, ஆனால் முன்பதிவு உறுதிப்படுத்தப்படும்.",
            "zh": "请注意，我们的日历同步暂时延迟——您的预约仍会确认。",
        },
        ServiceMode.EMERGENCY: {
            "en": "I'm sorry, our booking system is currently unavailable. Let me connect you to a staff member who can help.",
            "ms": "Maaf, sistem tempahan kami tidak tersedia buat masa ini. Saya akan sambungkan anda ke petugas kami.",
            "ta": "மன்னிக்கவும், முன்பதிவு அமைப்பு இப்போது கிடைக்கவில்லை. ஊழியரிடம் இணைக்கிறேன்.",
            "zh": "抱歉，预约系统暂时无法使用，我为您转接工作人员。",
        },
    }
    return notices.get(mode, {}).get(language) or notices.get(mode, {}).get("en")
