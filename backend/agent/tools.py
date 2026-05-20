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
        """Check if a date/time slot is available for booking.

        Args:
            date: Date in YYYY-MM-DD format
            time_slot: Time in HH:MM 24-hour format
            service: Service type requested
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
            return f"Sorry, {date} at {time_slot} is already taken. Would you like a different time?"
        return f"{date} at {time_slot} is available. Shall I book that for you?"

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
        """Create a confirmed booking. Always call check_availability first.

        Args:
            name: Customer full name
            phone: Customer phone number
            date: Date in YYYY-MM-DD format
            time_slot: Time in HH:MM 24-hour format
            service: Service type
            notes: Special requests or notes
        """
        # Double-booking guard — re-verify slot is still free before inserting
        conflict = (
            db.table("bookings")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("booking_date", date)
            .eq("booking_time", time_slot)
            .eq("status", "confirmed")
            .execute()
        )
        if conflict.data:
            return f"Sorry, {date} at {time_slot} was just taken. Please choose a different time."

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
        return f"Done! Booking confirmed for {name} on {date} at {time_slot} for {service}."

    @function_tool
    async def lookup_booking(context: RunContext, phone: str) -> str:
        """Look up existing bookings by customer phone number.

        Args:
            phone: Customer phone number
        """
        contact_resp = (
            db.table("contacts")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone", phone)
            .execute()
        )
        if not contact_resp.data:
            return "No bookings found for that number. Would you like to make a new booking?"

        contact_id = contact_resp.data[0]["id"]
        resp = (
            db.table("bookings")
            .select("id, booking_date, booking_time, service, status")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .eq("status", "confirmed")
            .order("booking_date", desc=False)
            .limit(3)
            .execute()
        )
        if not resp.data:
            return "No upcoming bookings found for that number."
        results = "; ".join(
            f"{r['service']} on {r['booking_date']} at {r['booking_time']}"
            for r in resp.data
        )
        return f"Upcoming bookings: {results}."

    @function_tool
    async def cancel_booking(
        context: RunContext,
        phone: str,
        date: str,
        time_slot: str,
    ) -> str:
        """Cancel an existing confirmed booking.

        Args:
            phone: Customer phone number
            date: Date of booking in YYYY-MM-DD format
            time_slot: Time of booking in HH:MM 24-hour format
        """
        contact_resp = (
            db.table("contacts")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone", phone)
            .execute()
        )
        if not contact_resp.data:
            return "I could not find any bookings for that number."

        contact_id = contact_resp.data[0]["id"]
        resp = (
            db.table("bookings")
            .update({"status": "cancelled"})
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .eq("booking_date", date)
            .eq("booking_time", time_slot)
            .eq("status", "confirmed")
            .execute()
        )
        if not resp.data:
            return f"I could not find a confirmed booking on {date} at {time_slot} for that number."
        return f"Done. Your booking on {date} at {time_slot} has been cancelled."

    @function_tool
    async def reschedule_booking(
        context: RunContext,
        phone: str,
        old_date: str,
        old_time_slot: str,
        new_date: str,
        new_time_slot: str,
    ) -> str:
        """Reschedule an existing booking to a new date and time.

        Args:
            phone: Customer phone number
            old_date: Current booking date in YYYY-MM-DD format
            old_time_slot: Current booking time in HH:MM 24-hour format
            new_date: New date in YYYY-MM-DD format
            new_time_slot: New time in HH:MM 24-hour format
        """
        # Check new slot availability first
        conflict = (
            db.table("bookings")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("booking_date", new_date)
            .eq("booking_time", new_time_slot)
            .eq("status", "confirmed")
            .execute()
        )
        if conflict.data:
            return f"Sorry, {new_date} at {new_time_slot} is already taken. Would you like a different time?"

        contact_resp = (
            db.table("contacts")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone", phone)
            .execute()
        )
        if not contact_resp.data:
            return "I could not find any bookings for that number."

        contact_id = contact_resp.data[0]["id"]
        resp = (
            db.table("bookings")
            .update({"booking_date": new_date, "booking_time": new_time_slot})
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .eq("booking_date", old_date)
            .eq("booking_time", old_time_slot)
            .eq("status", "confirmed")
            .execute()
        )
        if not resp.data:
            return f"I could not find a confirmed booking on {old_date} at {old_time_slot}."
        return f"Done! Your booking has been moved to {new_date} at {new_time_slot}."

    @function_tool
    async def transfer_to_human(
        context: RunContext,
        reason: str,
    ) -> str:
        """Transfer the caller to a human agent when the issue is too complex,
        caller is upset, or explicitly requests a human.

        Args:
            reason: Brief reason for the transfer
        """
        # Log escalation
        try:
            db.table("escalations").insert({
                "tenant_id": tenant_id,
                "reason": reason,
                "source": "voice",
                "status": "pending",
            }).execute()
        except Exception:
            pass

        return (
            "I understand. Let me transfer you to one of our team members right away. "
            "Please hold for a moment."
        )

    @function_tool
    async def answer_faq(
        context: RunContext,
        question: str,
    ) -> str:
        """Answer frequently asked questions about the business.

        Args:
            question: The caller's question
        """
        try:
            config_resp = (
                db.table("tenant_settings")
                .select("faqs")
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            faqs = config_resp.data.get("faqs") or [] if config_resp.data else []
        except Exception:
            faqs = []

        if not faqs:
            return "I don't have specific information on that. Would you like me to transfer you to someone who can help?"

        question_lower = question.lower()
        for faq in faqs:
            keywords = faq.get("q", "").lower().split()
            if any(kw in question_lower for kw in keywords if len(kw) > 3):
                return faq.get("a", "I don't have information on that.")

        return "I don't have a specific answer for that. Shall I transfer you to our team for more details?"

    return [
        check_availability,
        create_booking,
        lookup_booking,
        cancel_booking,
        reschedule_booking,
        transfer_to_human,
        answer_faq,
    ]
