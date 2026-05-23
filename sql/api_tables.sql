-- VoiceAI API tables
-- Run once in Supabase SQL Editor.
-- Does NOT touch voice_sessions, bookings, contacts, or call_logs.

-- LiveKit webhook event log (new table, no conflict)
CREATE TABLE IF NOT EXISTS livekit_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type   TEXT NOT NULL,
    room_name    TEXT,
    raw          TEXT,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_livekit_events_room
    ON livekit_events (room_name);

CREATE INDEX IF NOT EXISTS idx_livekit_events_type
    ON livekit_events (event_type, received_at DESC);

GRANT ALL ON livekit_events TO service_role;
GRANT SELECT ON livekit_events TO authenticated;
