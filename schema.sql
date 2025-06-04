-- schema.sql for Nightingale Application

-- Extension for UUID generation if needed for primary keys (optional)
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table for Users
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(255) PRIMARY KEY,         -- WhatsApp ID (e.g., 'whatsapp:+14155238886')
    name VARCHAR(255),                        -- User's name, if provided/retrieved
    is_wtw_employee BOOLEAN DEFAULT FALSE,
    wtw_handbook_sent_at TIMESTAMPTZ,          -- Timestamp when WTW handbook was sent
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table for Conversations (Sessions)
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    openai_thread_id VARCHAR(255) UNIQUE,
    current_sst_step VARCHAR(100),             -- e.g., 'INIT', 'SST_STEP_1_FRAME', 'SST_COMPLETED_PENDING_FOLLOW_UP'
    conversation_state_json JSONB,             -- Stores temporary data, history, current context for OpenAI
                                               -- Example: {"history": [...], "user_initial_problem": "...", "user_insight_from_step3": "...", "next_step_action_proposed": "..."}
    last_interaction_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,            -- Mark false if session is explicitly ended or escalated beyond AI
    escalated_at TIMESTAMPTZ,                  -- Timestamp if the conversation was escalated
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table for Session Outcomes (after each SST session)
CREATE TABLE IF NOT EXISTS session_outcomes (
    outcome_id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, -- Denormalized for easier querying
    insight_text TEXT,                         -- The "one clear insight"
    action_step_text TEXT,                     -- The "one clear next step"
    session_completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table for Scheduled Follow-ups
CREATE TABLE IF NOT EXISTS scheduled_follow_ups (
    follow_up_id SERIAL PRIMARY KEY,
    outcome_id INTEGER REFERENCES session_outcomes(outcome_id) ON DELETE SET NULL, -- Link to the session that prompted this
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scheduled_time TIMESTAMPTZ NOT NULL,       -- When the follow-up should be sent
    follow_up_message_template TEXT,           -- Specific message template if needed, otherwise default
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'SENT', 'USER_REPLIED', 'COMPLETED_NO_REPLY'
    sent_at TIMESTAMPTZ,                       -- Actual time the follow-up was sent
    user_reply_at TIMESTAMPTZ,                 -- Time of user's reply to the follow-up
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table for Longitudinal Progress Tracking
CREATE TABLE IF NOT EXISTS progress_tracking (
    progress_id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    outcome_id INTEGER REFERENCES session_outcomes(outcome_id) ON DELETE SET NULL, -- Optional: Link to the session where this action was decided
    action_taken TEXT NOT NULL,                -- The "small step" the user tried
    reported_outcome TEXT,                     -- How it went, e.g., "helped a lot", "didn't change much"
    action_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- When the action was reported/logged
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table for Messages (Optional, for full conversation logging and debugging)
-- Consider partitioning this table by date if it grows very large.
CREATE TABLE IF NOT EXISTS messages (
    message_id BIGSERIAL PRIMARY KEY,          -- Use BIGSERIAL for very high volume
    conversation_id INTEGER REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    sender_type VARCHAR(10) NOT NULL CHECK (sender_type IN ('USER', 'AI')), -- 'USER' or 'AI'
    content TEXT,
    wati_message_id VARCHAR(255) UNIQUE,       -- Original message ID from WATI, if available (for incoming)
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- Timestamp of the message
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- Triggers to update 'updated_at' timestamps automatically
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to tables that have 'updated_at'
CREATE TRIGGER set_timestamp_users
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION trigger_set_timestamp();

CREATE TRIGGER set_timestamp_conversations
BEFORE UPDATE ON conversations
FOR EACH ROW
EXECUTE FUNCTION trigger_set_timestamp();

CREATE TRIGGER set_timestamp_scheduled_follow_ups
BEFORE UPDATE ON scheduled_follow_ups
FOR EACH ROW
EXECUTE FUNCTION trigger_set_timestamp();


-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_is_active ON conversations(is_active);
CREATE INDEX IF NOT EXISTS idx_session_outcomes_user_id ON session_outcomes(user_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_follow_ups_user_id ON scheduled_follow_ups(user_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_follow_ups_status_scheduled_time ON scheduled_follow_ups(status, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_progress_tracking_user_id ON progress_tracking(user_id);
CREATE INDEX IF NOT EXISTS idx_progress_tracking_action_timestamp ON progress_tracking(action_timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);

COMMENT ON COLUMN users.user_id IS 'WhatsApp ID (e.g., ''whatsapp:+14155238886'')';
COMMENT ON COLUMN conversations.current_sst_step IS 'e.g., ''INIT'', ''SST_STEP_1_FRAME'', ''SST_COMPLETED_PENDING_FOLLOW_UP''';
COMMENT ON COLUMN conversations.conversation_state_json IS 'Stores temporary data, history, current context for OpenAI. Example: {"history": [...], "user_initial_problem": "...", "user_insight_from_step3": "...", "next_step_action_proposed": "..."}';
COMMENT ON COLUMN scheduled_follow_ups.status IS '''PENDING'', ''SENT'', ''USER_REPLIED'', ''COMPLETED_NO_REPLY''';
COMMENT ON COLUMN messages.sender_type IS '''USER'' or ''AI''';

-- You might want to add specific users/roles and grant permissions here
-- e.g., CREATE ROLE nightingale_app_user LOGIN PASSWORD 'your_password';
-- GRANT CONNECT ON DATABASE your_database_name TO nightingale_app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nightingale_app_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nightingale_app_user;