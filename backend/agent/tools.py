from livekit.agents import function_tool, RunContext
from agent.config_loader import get_supabase


def get_tool_definitions(tenant_id: str) -> list:
    db = get_supabase()

    @function_tool
    async def check_availability(
        context: RunContext,
        date: str,
        time_slot: str,
        service: str = "General",
    ) -> str:
        """Check if a date/time is available for booking.

        Args:
            date: Date in YYYY-MM-DD
            time_slot: Time in HH:MM 24-hour format
            service: Service type
        """
        resp = (
            db.table("bookings")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("booking_date", date)
            .eq("booking_time", time_slot)
            .eq("status", "confirmed")
            .execute()
        )
        if resp.data:
            return f"Sorry, {date} at {time_slot} is taken. Different time?"
        return f"{date} at {time_slot} is available. Book it?"

    @function_tool
    async def create_booking(
        context: RunContext,
        name: str,
        phone: str,
        date: str,
        time_slot: str,
        service: str = "General",
        notes: str = "",
    ) -> str:
        """Create a booking.

        Args:
            name: Full name
            phone: Phone number
            date: YYYY-MM-DD
            time_slot: HH:MM 24-hour
            service: Service type
            notes: Special requests
        """
        contact_resp = (
            db.table("contacts")
            .upsert(
                {"tenant_id": tenant_id, "phone": phone, "name": name},
                on_conflict="tenant_id,phone",
            )
            .execute()
        )
        contact_id = contact_resp.data[0]["id"] if contact_resp.data else None

        db.table("bookings").insert({
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "booking_date": date,
            "booking_time": time_slot,
            "service": service,
            "notes": notes,
            "status": "confirmed",
            "source": "voice",
        }).execute()
        return f"Confirmed for {name} on {date} at {time_slot}."

    @function_tool
    async def lookup_booking(context: RunContext, phone: str) -> str:
        """Look up bookings by phone.

        Args:
            phone: Phone number
        """
        resp = (
            db.table("bookings")
            .select("booking_date, booking_time, service, status")
            .eq("tenant_id", tenant_id)
            .order("booking_date", desc=True)
            .limit(3)
            .execute()
        )
        if not resp.data:
            return "No bookings found. Make a new one?"
        results = "; ".join(
            f"{r['service']} on {r['booking_date']} at {r['booking_time']} ({r['status']})"
            for r in resp.data
        )
        return f"Recent bookings: {results}."

    return [check_availability, create_booking, lookup_booking]
