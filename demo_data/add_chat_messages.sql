-- =============================================================
-- Parabellum ISOS - Chat between accounts
-- =============================================================
-- Adds the chat_messages table used by the floating chat button.
-- Run ONCE on your EXISTING database (Supabase: SQL Editor > paste > Run).
-- Safe to run again - it does nothing if the table already exists.
-- Deleting an account also deletes that account's conversations.
-- =============================================================

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id   SERIAL PRIMARY KEY,
    sender_id    INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    recipient_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    body         TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 500),
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at      TIMESTAMPTZ,
    CHECK (sender_id <> recipient_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_pair   ON chat_messages (sender_id, recipient_id, message_id);
CREATE INDEX IF NOT EXISTS idx_chat_unread ON chat_messages (recipient_id) WHERE read_at IS NULL;
