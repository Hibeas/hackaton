-- Run once in Supabase: SQL Editor → New query → Run
-- Project ref: jqmdskafhpbppgfrekxs

-- ===========================
-- Traffic observations (ML / anomaly engine)
-- ===========================
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

-- ===========================
-- App users (operators / spedycje)
-- ===========================
-- Create base table (works on fresh DB and if table already exists from earlier run)
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migration: add phone if table was created before this column existed
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_e164 TEXT;

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone_e164);

-- ===========================
-- TMS — canonical model + mock armator MSC
-- FireTMS-style: internal schema, swappable carrier adapters
-- ===========================
CREATE TABLE IF NOT EXISTS tms_carriers (
  provider_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  adapter TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  description_pl TEXT
);

CREATE TABLE IF NOT EXISTS tms_slot_templates (
  provider_id TEXT NOT NULL REFERENCES tms_carriers(provider_id),
  slot_id TEXT NOT NULL,
  terminal_code TEXT NOT NULL,
  port_id TEXT NOT NULL,
  start_hour INT NOT NULL,
  start_minute INT NOT NULL DEFAULT 0,
  duration_minutes INT NOT NULL DEFAULT 30,
  container_count INT NOT NULL DEFAULT 1,
  booking_ref TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed',
  corridor_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY (provider_id, slot_id)
);

CREATE TABLE IF NOT EXISTS tms_speditions (
  provider_id TEXT NOT NULL REFERENCES tms_carriers(provider_id),
  spedition_id TEXT NOT NULL,
  company_name TEXT NOT NULL,
  contact_name TEXT NOT NULL,
  phone_e164 TEXT NOT NULL,
  email TEXT,
  PRIMARY KEY (provider_id, spedition_id)
);

CREATE TABLE IF NOT EXISTS tms_spedition_slots (
  provider_id TEXT NOT NULL,
  spedition_id TEXT NOT NULL,
  slot_id TEXT NOT NULL,
  PRIMARY KEY (provider_id, spedition_id, slot_id),
  FOREIGN KEY (provider_id, spedition_id) REFERENCES tms_speditions(provider_id, spedition_id),
  FOREIGN KEY (provider_id, slot_id) REFERENCES tms_slot_templates(provider_id, slot_id)
);

CREATE INDEX IF NOT EXISTS idx_tms_slot_templates_terminal
  ON tms_slot_templates (provider_id, terminal_code);

CREATE INDEX IF NOT EXISTS idx_tms_speditions_phone
  ON tms_speditions (phone_e164);

-- ===========================
-- Seed: mock armator MSC (gate slot reservations)
-- ===========================
INSERT INTO tms_carriers (provider_id, display_name, adapter, active, description_pl)
VALUES (
  'mock_msc',
  'Mock MSC Gate TMS',
  'mock_msc_v1',
  TRUE,
  'Symulowany adapter armatora MSC — sloty bramowe i spedycje w formacie wewnętrznym Port-AI.'
)
ON CONFLICT (provider_id) DO NOTHING;

INSERT INTO tms_slot_templates (
  provider_id, slot_id, terminal_code, port_id,
  start_hour, start_minute, duration_minutes,
  container_count, booking_ref, status, corridor_ids
) VALUES
  ('mock_msc', 'SLOT-DCT-0800', 'DCT', 'gdynia', 8, 0, 30, 2, 'MSC-BKG-2024-884', 'confirmed', '["trasa_sucharskiego","tunel_martwa_wisla"]'::jsonb),
  ('mock_msc', 'SLOT-DCT-1400', 'DCT', 'gdynia', 14, 0, 30, 1, 'MSC-BKG-2024-901', 'confirmed', '["trasa_sucharskiego","wezel_s7_sucharskiego"]'::jsonb),
  ('mock_msc', 'SLOT-BCT-0930', 'BCT', 'gdynia', 9, 30, 30, 2, 'MSC-BKG-2024-712', 'confirmed', '["baltic_hub_gate","marynarki_polskiej"]'::jsonb),
  ('mock_msc', 'SLOT-GCT-1000', 'GCT', 'gdynia', 10, 0, 30, 3, 'MSC-BKG-2024-556', 'confirmed', '["estakada_kwiatkowskiego","janka_wisniewskiego"]'::jsonb),
  ('mock_msc', 'SLOT-GCT-1500', 'GCT', 'gdynia', 15, 0, 30, 2, 'MSC-BKG-2024-603', 'confirmed', '["ul_polska","s6_wezel_estakada"]'::jsonb),
  ('mock_msc', 'SLOT-PLSZZ-1100', 'PLSZZ', 'szczecin', 11, 0, 45, 1, 'MSC-BKG-2024-441', 'confirmed', '["s3_swinoujscie","wezel_s3_port"]'::jsonb)
ON CONFLICT (provider_id, slot_id) DO NOTHING;

INSERT INTO tms_speditions (
  provider_id, spedition_id, company_name, contact_name, phone_e164, email
) VALUES
  ('mock_msc', 'SPD-TRANS-BALTIC', 'Trans-Baltic Sp. z o.o.', 'Jan Kowalski', '+48728538889', 'dispatch@trans-baltic.pl'),
  ('mock_msc', 'SPD-NORD-LOG', 'NordLog Spedition', 'Anna Nowak', '+48728538889', 'ops@nordlog.pl'),
  ('mock_msc', 'SPD-GDY-TIR', 'Gdynia TIR Express', 'Piotr Wiśniewski', '+48728538889', 'tir@gdy-express.pl'),
  ('mock_msc', 'SPD-WEST-PORT', 'West Port Cargo', 'Marek Lewandowski', '+48728538889', 'cargo@westport.pl')
ON CONFLICT (provider_id, spedition_id) DO NOTHING;

INSERT INTO tms_spedition_slots (provider_id, spedition_id, slot_id) VALUES
  ('mock_msc', 'SPD-TRANS-BALTIC', 'SLOT-DCT-0800'),
  ('mock_msc', 'SPD-TRANS-BALTIC', 'SLOT-DCT-1400'),
  ('mock_msc', 'SPD-NORD-LOG', 'SLOT-BCT-0930'),
  ('mock_msc', 'SPD-GDY-TIR', 'SLOT-GCT-1000'),
  ('mock_msc', 'SPD-GDY-TIR', 'SLOT-GCT-1500'),
  ('mock_msc', 'SPD-WEST-PORT', 'SLOT-PLSZZ-1100')
ON CONFLICT DO NOTHING;
