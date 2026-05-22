-- Maya Voice Receptionist — Database Indexes
-- Run once in Supabase SQL Editor to speed up all agent queries.

-- contacts: look up by phone (used on every call)
CREATE INDEX IF NOT EXISTS idx_contacts_tenant_phone
    ON contacts (tenant_id, phone);

-- bookings: find active bookings by contact
CREATE INDEX IF NOT EXISTS idx_bookings_contact_status
    ON bookings (tenant_id, contact_id, status, scheduled_at DESC);

-- bookings: look up by scheduled time (double-booking guard)
CREATE INDEX IF NOT EXISTS idx_bookings_scheduled_at
    ON bookings (tenant_id, scheduled_at)
    WHERE status IN ('confirmed', 'rescheduled', 'pending');

-- availability_slots: check a specific slot
CREATE INDEX IF NOT EXISTS idx_slots_date_time
    ON availability_slots (tenant_id, slot_date, slot_time)
    WHERE is_available = TRUE;

-- voice_sessions: end-of-call update
CREATE INDEX IF NOT EXISTS idx_voice_sessions_room
    ON voice_sessions (livekit_room_id);

-- call_logs: reporting queries
CREATE INDEX IF NOT EXISTS idx_call_logs_tenant_created
    ON call_logs (tenant_id, created_at DESC);

-- conversation_states table (new — run this CREATE before the index)
CREATE TABLE IF NOT EXISTS conversation_states (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL,
    livekit_room_id TEXT NOT NULL,
    state         JSONB NOT NULL DEFAULT '{}',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, livekit_room_id)
);

CREATE INDEX IF NOT EXISTS idx_conv_states_room
    ON conversation_states (tenant_id, livekit_room_id);
