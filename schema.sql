-- Bonfire Pediatrics Database Schema
-- PostgreSQL schema for Nightingale AI Parenting Coach system

-- Create database extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enum Types
CREATE TYPE user_mode AS ENUM ('coaching', 'concierge', 'undefined');
CREATE TYPE monthly_summary_option_status AS ENUM ('accepted', 'not_asked', 'dismissed');
CREATE TYPE session_status AS ENUM ('active', 'completed', 'abandoned');
CREATE TYPE coaching_session_status AS ENUM ('active', 'completed', 'abandoned', 'cancelled');
CREATE TYPE subscription_status AS ENUM ('pre_trial', 'trialing', 'converted_paid', 'trial_expired', 'canceled');
CREATE TYPE assessment_type AS ENUM ('iq_giftedness', 'depression_anxiety_ptsd', 'adhd', 'asd_autism', 'global_developmental_delay', 'intellectual_disability');
CREATE TYPE preferred_time AS ENUM ('weekday_morning', 'weekday_afternoon', 'weekend_morning', 'weekend_afternoon', 'no_preference', 'specific_datetime');
CREATE TYPE booking_status AS ENUM ('collecting_info', 'data_complete', 'sent_to_clinics', 'clinic_suggested', 'payment_requested', 'completed');
CREATE TYPE crisis_level AS ENUM ('none', 'detected', 'confirmed', 'escalated');

-- Users table (Parents)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    whatsapp_id VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    phone VARCHAR(20),
    email VARCHAR(255),
    postal_code VARCHAR(10),

    -- Trial & Subscription Info
    trial_start_date DATE,
    subscription_status subscription_status DEFAULT 'pre_trial',

    -- Coaching Session Tracking
    coaching_session_count INTEGER DEFAULT 0,
    last_coaching_date TIMESTAMP WITH TIME ZONE,

    -- Subscription info
    stripe_customer_id VARCHAR(255),
    subscription_id VARCHAR(255),
    monthly_summary_option monthly_summary_option_status DEFAULT 'not_asked',

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Children table
CREATE TABLE children (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parent_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    age INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Conversations
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode user_mode NOT NULL,
    status session_status DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Coaching Sessions (SST Framework sessions)
CREATE TABLE coaching_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    session_number INTEGER DEFAULT 1,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status coaching_session_status DEFAULT 'active',

    -- Session info
    parent_insight TEXT,
    micro_step TEXT,
    follow_up_scheduled BOOLEAN DEFAULT FALSE,
    follow_up_date TIMESTAMP WITH TIME ZONE,
    follow_up_sent_at TIMESTAMP WITH TIME ZONE,
    crisis_level crisis_level DEFAULT 'none',
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Concierge Bookings
CREATE TABLE concierge_bookings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    child_id UUID REFERENCES children(id),
    assessment_types assessment_type[] NOT NULL,
    preferred_time preferred_time,
    specific_datetime TIMESTAMP WITH TIME ZONE,
    status booking_status DEFAULT 'collecting_info',
    clinic_suggestions TEXT,
    payment_processed BOOLEAN DEFAULT FALSE,
    consent_form_sent BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Voice Calls
CREATE TABLE voice_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    concierge_booking_id UUID NOT NULL REFERENCES concierge_bookings(id) ON DELETE CASCADE,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    call_summary TEXT,
    booking_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Trial Nudges Tracking
CREATE TABLE trial_nudges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nudge_day INTEGER NOT NULL, -- 7, 14, 20, 28
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    user_responded BOOLEAN DEFAULT FALSE,
    response_text TEXT,
    UNIQUE(user_id, nudge_day)
);

-- Crisis Alerts
CREATE TABLE crisis_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    coaching_session_id UUID NOT NULL REFERENCES coaching_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    crisis_keywords TEXT[],
    user_confirmed_danger BOOLEAN,
    accepted_help BOOLEAN,
    alert_sent_to_doctor BOOLEAN DEFAULT FALSE,
    doctor_email VARCHAR(255) DEFAULT 'Dr.Reale@gmail.com',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Conversation Messages (for audit/history)
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender VARCHAR(50) NOT NULL, -- 'user' or 'nightingale'
    message_text TEXT NOT NULL,
    message_type VARCHAR(50), -- 'greeting', 'question', 'response', 'nudge', etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_users_trial_start ON users(trial_start_date) WHERE trial_start_date IS NOT NULL;
CREATE INDEX idx_coaching_sessions_conversation ON coaching_sessions(conversation_id);
CREATE INDEX idx_coaching_sessions_user ON coaching_sessions(user_id);
CREATE INDEX idx_concierge_bookings_conversation ON concierge_bookings(conversation_id);
CREATE INDEX idx_concierge_bookings_user ON concierge_bookings(user_id);
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_trial_nudges_user ON trial_nudges(user_id);
CREATE INDEX idx_crisis_alerts_created ON crisis_alerts(created_at);

-- Function to check if nudge can be sent. This will be invoked by Lambda function
CREATE OR REPLACE FUNCTION can_send_nudge_to_user(
    p_user_id UUID,
    p_nudge_day INTEGER -- e.g., 7, 14, 20, 28
) RETURNS BOOLEAN AS $$
DECLARE
    v_subscription_status subscription_status;
    v_nudge_sent BOOLEAN;
BEGIN
    -- Kiểm tra trạng thái hiện tại của user
    SELECT subscription_status
    INTO v_subscription_status
    FROM users
    WHERE id = p_user_id;

    -- Nếu user không còn trong trial, chắc chắn không gửi
    IF v_subscription_status != 'trialing' THEN
        RETURN FALSE;
    END IF;

    -- Kiểm tra xem nudge cho ngày này đã được gửi chưa (để tránh gửi lại nếu Lambda bị trigger nhầm)
    SELECT EXISTS (
        SELECT 1 FROM trial_nudges
        WHERE user_id = p_user_id AND nudge_day = p_nudge_day
    )
    INTO v_nudge_sent;

    IF v_nudge_sent THEN
        RETURN FALSE;
    END IF;

    -- Nếu tất cả điều kiện đều qua, cho phép gửi
    RETURN TRUE;

END;
$$ LANGUAGE 'plpgsql';

-- Functions for common operations
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_conversations_updated_at BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_concierge_bookings_updated_at BEFORE UPDATE ON concierge_bookings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Sample data insertion (optional)
-- INSERT INTO users (name, email) VALUES ('Jane Doe', 'jane@example.com');
-- INSERT INTO conversations (user_id, mode) 
-- VALUES ((SELECT id FROM users WHERE email = 'jane@example.com'), 'coaching');