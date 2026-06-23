-- Run this alone if schema.sql failed on idx_users_phone (users table existed without phone_e164)
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_e164 TEXT;

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone_e164);
