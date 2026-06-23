-- Run once in Supabase: SQL Editor → New query → Run
-- Project: port-ai observation history for anomaly engine

CREATE TABLE IF NOT EXISTS corridor_observations (
  id BIGSERIAL PRIMARY KEY,
  corridor_id TEXT NOT NULL,
  port_id TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  payload_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_corridor_time
  ON corridor_observations (corridor_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_corridor_obs_port_time
  ON corridor_observations (port_id, observed_at DESC);
