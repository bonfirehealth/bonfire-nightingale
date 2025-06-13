from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import pytz
import psycopg2
from psycopg2.extensions import cursor as Psycopg2Cursor
from config import logger, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

# Global connection for Lambda reuse
db_conn = None


def get_db_connection() -> psycopg2.extensions.connection:
    """
    Get reusable database connection for Lambda invocation.
    
    Returns:
        Active PostgreSQL connection
        
    Raises:
        psycopg2.Error: If connection fails
    """
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
            logger.info("Database connection established")
        except psycopg2.Error as e:
            logger.error(f"Database connection failed: {e}")
            raise
    return db_conn


def _row_to_dict(cursor: Psycopg2Cursor, row: tuple) -> Dict[str, Any]:
    """Convert database row tuple to dictionary using cursor description."""
    if not row:
        return {}
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


# =============================================================================
# PARENT OPERATIONS
# =============================================================================

def get_or_create_parent(cursor: Psycopg2Cursor, full_name: str, whatsapp_id: str) -> Dict[str, Any]:
    """
    Find parent by phone number or create new one.
    
    Args:
        cursor: Database cursor
        full_name: Parent's full name
        whatsapp_id: Parent's whatsapp id
        
    Returns:
        Parent data as dictionary
    """
    cursor.execute(
        """
        INSERT INTO parents (full_name, whatsapp_id, phone_number)
        VALUES (%s, %s, %s)
        ON CONFLICT (whatsapp_id) DO UPDATE 
        SET full_name = EXCLUDED.full_name
        RETURNING *
        """,
        (full_name, whatsapp_id, whatsapp_id)
    )
    
    parent = cursor.fetchone()
    if not parent:
        raise Exception("Failed to create or retrieve parent record")
        
    return _row_to_dict(cursor, parent)


def get_parent_by_id(cursor: Psycopg2Cursor, parent_id: int) -> Dict[str, Any]:
    """
    Get parent by ID.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        
    Returns:
        Parent data as dictionary
        
    Raises:
        ValueError: If parent not found
    """
    cursor.execute("SELECT * FROM parents WHERE id = %s", (parent_id,))
    parent = cursor.fetchone()
    
    if not parent:
        raise ValueError(f"Parent with ID {parent_id} not found")
        
    return _row_to_dict(cursor, parent)


def update_parent_contact_info(cursor: Psycopg2Cursor, parent_id: int, contact_data: Dict[str, Any]) -> None:
    """
    Update parent's contact information.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        contact_data: Contact information to update
    """
    allowed_fields = {"full_name", "whatsapp_id", "phone_number", "email", "postal_code"}
    updates = {k: v for k, v in contact_data.items() if k in allowed_fields and v}
    
    if not updates:
        return
    
    set_clause = ", ".join(f"{field} = %s" for field in updates.keys())
    cursor.execute(
        f"UPDATE parents SET {set_clause} WHERE id = %s",
        (*updates.values(), parent_id)
    )
    logger.info(f"Updated contact info for parent {parent_id}")


def update_parent_preferences(cursor: Psycopg2Cursor, parent_id: int, preferences: Dict[str, Any]) -> None:
    """
    Update parent's preferences and settings.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        preferences: Preferences to update
    """
    allowed_fields = {"monthly_summary_opted_in", "current_mode", "current_step", "subscription_status"}
    updates = {k: v for k, v in preferences.items() if k in allowed_fields}
    
    if not updates:
        return
    
    set_clause = ", ".join(f"{field} = %s" for field in updates.keys())
    cursor.execute(
        f"UPDATE parents SET {set_clause} WHERE id = %s",
        (*updates.values(), parent_id)
    )


def activate_trial_plan(cursor: Psycopg2Cursor, parent_id: int) -> None:
    """
    Activate trial plan for parent.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
    """
    # Check if user's subscription status is `pre_trial`
    cursor.execute(
        "SELECT subscription_status FROM parents WHERE id = %s",
        (parent_id,)
    )
    result = cursor.fetchone()
    if result is None:
        raise ValueError(f"Parent with ID {parent_id} not found")
        
    subscription_status = result[0]
    logger.debug(f"Parent {parent_id} subscription status: {subscription_status}")
    
    if subscription_status != "pre_trial":
        return

    # Only activate trial if parent's subscription status is `pre_trial`
    cursor.execute(
        """
        UPDATE parents 
        SET subscription_status = 'trialing', trial_start_date = NOW()
        WHERE id = %s AND subscription_status = 'pre_trial'
        """,
        (parent_id,)
    )
    logger.info(f"Trial activated for parent {parent_id}")


def increment_session_count(cursor: Psycopg2Cursor, parent_id: int) -> None:
    """
    Increment session count for parent.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
    """
    cursor.execute(
        """
        UPDATE parents 
        SET session_count = session_count + 1
        WHERE (subscription_status = 'trialing' OR subscription_status = 'active_paid') AND id = %s
        """,
        (parent_id,)
    )


# =============================================================================
# CHILD OPERATIONS
# =============================================================================

def upsert_child(cursor: Psycopg2Cursor, parent_id: int, child_name: str, child_age: Optional[int]) -> Dict[str, Any]:
    """
    Create or update child record.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        child_name: Child's name
        child_age: Child's age (optional)
        
    Returns:
        Child data as dictionary
        
    Raises:
        ValueError: If child age is invalid
    """
    if child_age is not None and (child_age < 0 or child_age > 30):
        raise ValueError("Child age must be between 0 and 30")
    
    # Calculate date of birth if age provided
    date_of_birth = None
    if child_age is not None:
        date_of_birth = datetime.now(pytz.utc) - timedelta(days=child_age * 365)
    
    # Try to find existing child
    if date_of_birth:
        cursor.execute(
            "SELECT * FROM children WHERE parent_id = %s AND name = %s AND date_of_birth = %s",
            (parent_id, child_name, date_of_birth)
        )
    else:
        cursor.execute(
            "SELECT * FROM children WHERE parent_id = %s AND name = %s",
            (parent_id, child_name)
        )
    
    child = cursor.fetchone()
    if child:
        return _row_to_dict(cursor, child)
    
    # Create new child
    cursor.execute(
        """
        INSERT INTO children (parent_id, name, date_of_birth)
        VALUES (%s, %s, %s)
        RETURNING *
        """,
        (parent_id, child_name, date_of_birth)
    )
    new_child = cursor.fetchone()
    logger.info(f"New child created for parent {parent_id}")
    return _row_to_dict(cursor, new_child)


def get_children_by_parent(cursor: Psycopg2Cursor, parent_id: int) -> List[Dict[str, Any]]:
    """
    Get all children for a parent.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        
    Returns:
        List of child data dictionaries
    """
    cursor.execute("SELECT * FROM children WHERE parent_id = %s", (parent_id,))
    children = cursor.fetchall()
    return [_row_to_dict(cursor, child) for child in children]


def get_all_children(cursor: Psycopg2Cursor, parent_id: int) -> List[Dict[str, Any]]:
    """
    Get all children.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        
    Returns:
        List of child data dictionaries
    """
    cursor.execute("SELECT * FROM children WHERE parent_id = %s", (parent_id,))
    children = cursor.fetchall()
    return [_row_to_dict(cursor, child) for child in children]

# =============================================================================
# APPOINTMENT OPERATIONS
# =============================================================================

def create_appointment(cursor: Psycopg2Cursor, appointment_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create new appointment.
    
    Args:
        cursor: Database cursor
        appointment_data: Appointment details
        
    Returns:
        Created appointment data
    """
    required_fields = ["parent_id", "status", "assessment_type"]
    for field in required_fields:
        if field not in appointment_data:
            raise ValueError(f"Missing required field: {field}")
    
    cursor.execute(
        """
        INSERT INTO appointments (parent_id, status, preferred_time_slot, assessment_type, case_notes, urgency_level)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            appointment_data["parent_id"],
            appointment_data["status"],
            appointment_data.get("preferred_time_slot", ""),
            appointment_data["assessment_type"],
            appointment_data.get("case_notes", ""),
            appointment_data.get("urgency_level", "low")
        )
    )
    new_appointment = cursor.fetchone()
    logger.info(f"New appointment created for parent {appointment_data['parent_id']}")
    return _row_to_dict(cursor, new_appointment)


# =============================================================================
# COACHING SESSION OPERATIONS
# =============================================================================

def create_coaching_session(cursor: Psycopg2Cursor, parent_id: int) -> Dict[str, Any]:
    """
    Create new coaching session.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        
    Returns:
        Created session data
    """
    cursor.execute(
        """
        INSERT INTO coaching_sessions (parent_id, status)
        VALUES (%s, 'active')
        RETURNING *
        """,
        (parent_id,)
    )
    new_session = cursor.fetchone()
    logger.info(f"New coaching session created for parent {parent_id}")
    return _row_to_dict(cursor, new_session)


def get_active_coaching_session(cursor: Psycopg2Cursor, parent_id: int) -> Optional[Dict[str, Any]]:
    """
    Get active coaching session for parent.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        
    Returns:
        Active session data or None
    """
    cursor.execute(
        "SELECT * FROM coaching_sessions WHERE parent_id = %s AND status = 'active'",
        (parent_id,)
    )
    session = cursor.fetchone()
    return _row_to_dict(cursor, session) if session else None


def get_latest_coaching_session(cursor: Psycopg2Cursor, parent_id: int, status: str) -> Optional[Dict[str, Any]]:
    """
    Get latest coaching session with specific status.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        status: Session status to filter by
        
    Returns:
        Latest session data or None
    """
    cursor.execute(
        """
        SELECT * FROM coaching_sessions 
        WHERE parent_id = %s AND status = %s
        ORDER BY session_end_time DESC
        LIMIT 1
        """,
        (parent_id, status)
    )
    session = cursor.fetchone()
    return _row_to_dict(cursor, session) if session else None


def update_coaching_session(cursor: Psycopg2Cursor, session_id: int, updates: Dict[str, Any]) -> None:
    """
    Update coaching session with new data.
    
    Args:
        cursor: Database cursor
        session_id: Session ID to update
        updates: Fields to update
    """
    allowed_fields = {
        "status", "session_start_time", "session_end_time", "parent_insight", 
        "action_step", "follow_up_scheduled", "follow_up_sent_at", "follow_up_outcome",
        "monthly_summary_offered", "monthly_summary_opted_in"
    }
    
    filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered_updates:
        return
    
    set_clause = ", ".join(f"{field} = %s" for field in filtered_updates.keys())
    cursor.execute(
        f"UPDATE coaching_sessions SET {set_clause} WHERE id = %s",
        (*filtered_updates.values(), session_id)
    )

def should_schedule_nudges(cursor: Psycopg2Cursor, parent_id: int) -> bool:
    """
    Check if parent should receive nudges.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        
    Returns:
        True if any nudges should be scheduled, False otherwise
    """
    cursor.execute(
        """
        SELECT subscription_status, sent_nudge_day_7_soft_introduction, 
        sent_nudge_day_14_low_usage, sent_nudge_day_20_conversion,
        sent_nudge_day_28_final_reminder
        FROM parents WHERE id = %s
        """,
        (parent_id,)
    )
    result = cursor.fetchone()

    if result is None:
        raise ValueError(f"Parent with ID {parent_id} not found")
    
    subscription_status = result[0]
    sent_nudge_day_7_soft_introduction = result[1]
    sent_nudge_day_14_low_usage = result[2]
    sent_nudge_day_20_conversion = result[3]
    sent_nudge_day_28_final_reminder = result[4]
    
    logger.debug(f"Parent {parent_id} subscription status: {subscription_status}")

    if subscription_status == "pre_trial":
        # Move to `trialing` status
        cursor.execute(
            "UPDATE parents SET subscription_status = 'trialing' WHERE id = %s",
            (parent_id,)
        )
        subscription_status = "trialing"
    
    return (
        subscription_status == "trialing" and
        any([
            sent_nudge_day_7_soft_introduction == False, 
            sent_nudge_day_14_low_usage == False, 
            sent_nudge_day_20_conversion == False, 
            sent_nudge_day_28_final_reminder == False
        ])
    )

# =============================================================================
# ESCALATION OPERATIONS
# =============================================================================

def create_escalation_log(cursor: Psycopg2Cursor, parent_id: int, escalation_data: Dict[str, Any]) -> None:
    """
    Log escalation incident.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        escalation_data: Escalation context and details
    """
    allowed_fields = {"triggering_message", "escalation_type", "action_taken"}
    filtered_data = {k: v for k, v in escalation_data.items() if k in allowed_fields}
    
    if not filtered_data:
        logger.warning(f"No valid escalation data provided for parent {parent_id}")
        return
    
    field_names = list(filtered_data.keys())
    placeholders = ", ".join(["%s"] * len(field_names))
    field_clause = ", ".join(field_names)
    
    cursor.execute(
        f"""
        INSERT INTO escalations (parent_id, {field_clause})
        VALUES (%s, {placeholders})
        """,
        (parent_id, *filtered_data.values())
    )
    logger.info(f"Escalation logged for parent {parent_id}")


# =============================================================================
# MESSAGE OPERATIONS
# =============================================================================

def get_message_history(cursor: Psycopg2Cursor, parent_id: int, limit: int = 100) -> str:
    """
    Get formatted message history for AI context.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        limit: Maximum number of messages to retrieve
        
    Returns:
        Formatted message history string
    """
    cursor.execute(
        """
        SELECT sender, content FROM messages
        WHERE parent_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (parent_id, limit)
    )
    
    # Reverse to get chronological order
    messages = cursor.fetchall()[::-1]
    
    return "\n".join(f"{sender}: {content}" for sender, content in messages)


def log_message(cursor: Psycopg2Cursor, parent_id: int, sender: str, content: str) -> None:
    """
    Log message to database.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        sender: Message sender ('user' or 'ai')
        content: Message content
    """
    cursor.execute(
        """
        INSERT INTO messages (parent_id, sender, content)
        VALUES (%s, %s, %s)
        """,
        (parent_id, sender, content)
    )