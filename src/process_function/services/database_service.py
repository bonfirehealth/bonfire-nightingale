import psycopg2
from config import logger, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

db_conn = None

def get_db_connection():
    """Establishes a reusable database connection for the Lambda invocation."""
    global db_conn
    if db_conn is None or db_conn.closed:
        try:
            db_conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            logger.info("Database connection established successfully.")
        except psycopg2.Error as e:
            logger.error(f"Error connecting to PostgreSQL database: {e}")
            raise
    return db_conn

def get_or_create_user(db_conn, whatsapp_id):
    """
    Fetches the full context for a user.
    This is a "get-or-create" pattern.
    
    Args:
        db_conn: Database connection
        whatsapp_id: User's WhatsApp ID
        
    Returns:
        dict: User record with all fields
    """
    cur = db_conn.cursor()
    
    try:
        # 1. Try to get existing user with all fields
        cur.execute("""
            SELECT id, name, whatsapp_id, phone, email, postal_code,
                   trial_start_date, subscription_status, coaching_session_count, 
                   last_coaching_date, monthly_summary_option, created_at 
            FROM users 
            WHERE whatsapp_id = %s
        """, (whatsapp_id,))
        
        user = cur.fetchone()
        
        if user:
            # Convert to dict with column names for easier access
            columns = [desc[0] for desc in cur.description]
            user_dict = dict(zip(columns, user))
            return user_dict
            
        # 2. Create new user if not exists
        logger.info(f"Creating new user with whatsapp_id: {whatsapp_id}")
        
        cur.execute("""
            INSERT INTO users (whatsapp_id) 
            VALUES (%s) 
            RETURNING id, name, whatsapp_id, phone, email, postal_code,
                     trial_start_date, subscription_status, coaching_session_count, 
                     last_coaching_date, monthly_summary_option, created_at
        """, (whatsapp_id,))
        
        # Convert to dict with column names
        user = cur.fetchone()
        columns = [desc[0] for desc in cur.description]
        user_dict = dict(zip(columns, user))
        
        db_conn.commit()
        return user_dict
        
    except Exception as e:
        db_conn.rollback()
        logger.error(f"Error in get_or_create_user: {e}")
        raise
    finally:
        cur.close()

def get_or_create_conversation(db_conn, user_id):
    """
    Fetches the active conversation for a user or creates a new one.
    This is a "get-or-create" pattern.
    
    Args:
        db_conn: Database connection
        user_id: ID of the user
        
    Returns:
        dict: Conversation record with all fields
    """
    cur = db_conn.cursor()
    
    try:
        # 1. Try to get existing active conversation with all fields
        cur.execute("""
            SELECT id, user_id, mode, status, created_at, updated_at
            FROM conversations 
            WHERE user_id = %s AND status = 'active' 
            ORDER BY created_at DESC 
            LIMIT 1
        """, (user_id,))
        
        conversation = cur.fetchone()
        
        if conversation:
            # Convert to dict with column names for easier access
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, conversation))
            
        # 2. Create new conversation if none exists
        logger.info(f"Creating new conversation for user_id: {user_id}")
        
        cur.execute("""
            INSERT INTO conversations (user_id, mode, status) 
            VALUES (%s, 'undefined', 'active')
            RETURNING id, user_id, mode, status, created_at, updated_at
        """, (user_id,))
        
        # Convert to dict with column names
        conversation = cur.fetchone()
        columns = [desc[0] for desc in cur.description]
        conversation_dict = dict(zip(columns, conversation))
        
        db_conn.commit()
        return conversation_dict
        
    except Exception as e:
        db_conn.rollback()
        logger.error(f"Error in get_or_create_conversation: {e}")
        raise
    finally:
        cur.close()

def get_recent_messages(db_conn, conversation_id, limit=10):
    cur = db_conn.cursor()
    cur.execute("SELECT id, sender, message_text, message_type, created_at FROM messages WHERE conversation_id = %s ORDER BY created_at DESC LIMIT %s", (conversation_id, limit))
    messages = cur.fetchall()
    cur.close()
    messages = [dict(zip([desc[0] for desc in cur.description], message)) for message in messages]
    return messages

def check_trial_status(db_conn, user_id):
    cur = db_conn.cursor()
    cur.execute("SELECT trial_start_date, subscription_status, last_coaching_date FROM users WHERE id = %s", (user_id,))
    trial_info = cur.fetchone()
    cur.close()
    return dict(zip([desc[0] for desc in cur.description], trial_info))

def save_message(db_conn, conversation_id, sender, message_text, message_type):
    cur = db_conn.cursor()
    cur.execute("INSERT INTO messages (conversation_id, sender, message_text, message_type) VALUES (%s, %s, %s, %s)", (conversation_id, sender, message_text, message_type))
    db_conn.commit()
    cur.close()

def get_or_create_appointment(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get the latest active appointment
    cur.execute("SELECT id, booking_status, created_at FROM appointments WHERE user_id = %s and booking_status != 'cancelled' ORDER BY created_at DESC LIMIT 1", (user_id,))
    appointment = cur.fetchone()
    if not appointment:
        cur.execute("INSERT INTO appointments (user_id) VALUES (%s) RETURNING id, booking_status, created_at", (user_id,))
        appointment = cur.fetchone()
        conn.commit()
    appointment_id = appointment[0]
    
    return {
        "id": str(appointment_id),
        "booking_status": appointment[1],
        "created_at": str(appointment[2])
    }

def get_or_create_coaching_session(user_id, conversation_id):
    conn = get_db_connection()
    cur = conn.cursor()

    # Get the latest active coaching session
    cur.execute("SELECT id, conversation_id, session_number, started_at, completed_at, status, current_step, steps_completed, parent_insight, micro_action, follow_up_requested, follow_up_scheduled_for, follow_up_completed_at, follow_up_outcome, crisis_keywords_detected, crisis_escalated, escalation_reason FROM coaching_sessions WHERE user_id = %s and conversation_id = %s ORDER BY started_at DESC LIMIT 1", (user_id, conversation_id))
    coaching_session = cur.fetchone()
    if not coaching_session:
        cur.execute("INSERT INTO coaching_sessions (user_id, conversation_id) VALUES (%s, %s) RETURNING id, conversation_id, session_number, started_at, completed_at, status, current_step, steps_completed, parent_insight, micro_action, follow_up_requested, follow_up_scheduled_for, follow_up_completed_at, follow_up_outcome, crisis_keywords_detected, crisis_escalated, escalation_reason", (user_id, conversation_id))
        coaching_session = cur.fetchone()
        conn.commit()
    coaching_session_id = coaching_session[0]
    
    return {
        "id": str(coaching_session_id),
        "user_id": str(user_id),
        "conversation_id": str(conversation_id),
        "session_number": coaching_session[2],
        "started_at": str(coaching_session[3]),
        "completed_at": str(coaching_session[4]),
        "status": coaching_session[5],
        "current_step": coaching_session[6],
        "steps_completed": coaching_session[7],
        "parent_insight": coaching_session[8],
        "micro_action": coaching_session[9],
        "follow_up_requested": coaching_session[10],
        "follow_up_scheduled_for": str(coaching_session[11]),
        "follow_up_completed_at": str(coaching_session[12]),
        "follow_up_outcome": coaching_session[13],
        "crisis_keywords_detected": coaching_session[14],
        "crisis_escalated": coaching_session[15],
        "escalation_reason": coaching_session[16]
    }

def log_message(conversation_id, user_id, direction, content, wati_message_id=None):
    """Logs an inbound or outbound message to the database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (conversation_id, user_id, direction, content, wati_message_id) VALUES (%s, %s, %s, %s, %s)",
        (conversation_id, user_id, direction, content, wati_message_id)
    )
    conn.commit()
    cur.close()
    logger.info(f"Logged {direction} message for user {user_id}")

def process_state_updates(state_update):
    """
    Processes the state_update object from the AI response to update the database.
    This function needs to be very robust.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Update User
        if state_update.get('user', {}).get('updates'):
            user_id = state_update['user']['id']
            updates = state_update['user']['updates']
            # Build query dynamically but safely
            set_clauses = ", ".join([f"{key} = %s" for key in updates.keys()])
            values = list(updates.values())
            values.append(user_id)
            cur.execute(f"UPDATE users SET {set_clauses}, updated_at = NOW() WHERE id = %s", tuple(values))

        # Update Conversation
        if state_update.get('conversation', {}).get('updates'):
            convo_id = state_update['conversation']['id']
            updates = state_update['conversation']['updates']
            set_clauses = ", ".join([f"{key} = %s" for key in updates.keys()])
            values = list(updates.values())
            values.append(convo_id)
            cur.execute(f"UPDATE conversations SET {set_clauses} WHERE id = %s", tuple(values))

        # # Create New Records
        # if state_update.get('new_records'):
        #     for table_name, records in state_update['new_records'].items():
        #         for record_data in records:
        #             columns = ", ".join(record_data.keys())
        #             placeholders = ", ".join(["%s"] * len(record_data))
        #             values = tuple(record_data.values())
        #             cur.execute(f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})", values)
        
        if state_update.get('appointment', {}).get('updates'):
            appointment_id = state_update['appointment']['id']
            updates = state_update['appointment']['updates']
            set_clauses = ", ".join([f"{key} = %s" for key in updates.keys()])
            values = list(updates.values())
            values.append(appointment_id)
            cur.execute(f"UPDATE appointments SET {set_clauses} WHERE id = %s", tuple(values))

        conn.commit()
        logger.info("Successfully processed state updates.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to process state updates: {e}")
        raise
    finally:
        cur.close()