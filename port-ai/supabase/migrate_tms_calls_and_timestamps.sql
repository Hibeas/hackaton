-- Run in Supabase SQL Editor after schema.sql (idempotent)
-- Adds slot timestamps, at_risk tracking, and one-call-per-booking constraint.

ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS at_risk_since TIMESTAMPTZ;
ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS window_start_at TIMESTAMPTZ;
ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS window_end_at TIMESTAMPTZ;
ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS owner_user_id UUID;

CREATE INDEX IF NOT EXISTS idx_tms_slot_templates_owner
  ON tms_slot_templates (owner_user_id)
  WHERE owner_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS tms_slot_calls (
  id BIGSERIAL PRIMARY KEY,
  provider_id TEXT NOT NULL,
  booking_ref TEXT NOT NULL,
  slot_id TEXT NOT NULL,
  spedition_id TEXT,
  phone_e164 TEXT NOT NULL,
  call_sid TEXT,
  call_status TEXT NOT NULL DEFAULT 'initiated',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  answered_at TIMESTAMPTZ,
  CONSTRAINT tms_slot_calls_status_check
    CHECK (call_status IN ('initiated', 'answered', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_tms_slot_calls_booking
  ON tms_slot_calls (booking_ref, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tms_slot_calls_one_answered_per_booking
  ON tms_slot_calls (booking_ref)
  WHERE call_status = 'answered';

CREATE UNIQUE INDEX IF NOT EXISTS idx_tms_slot_calls_one_active_per_booking
  ON tms_slot_calls (booking_ref)
  WHERE call_status IN ('initiated', 'answered');

CREATE INDEX IF NOT EXISTS idx_tms_slot_templates_at_risk
  ON tms_slot_templates (provider_id, status)
  WHERE status = 'at_risk';
