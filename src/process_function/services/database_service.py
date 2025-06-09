import psycopg2
from psycopg2.extensions import cursor as Psycopg2Cursor
from config import logger, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

db_conn = None

def get_db_connection() -> psycopg2.extensions.connection:
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

def get_or_create_parent(cursor: Psycopg2Cursor, full_name: str, phone_number: str) -> dict:
    """
    Finds a parent by phone number. If not found, creates a new one.
    Returns the parent's data as a dictionary.

    Args:
        cursor (Cursor): The database cursor.
        full_name (str): The full name of the parent.
        phone_number (str): The phone number of the parent.
    
    Returns:
        dict: The parent's data as a dictionary.
    """
    cursor.execute("SELECT * FROM parents WHERE phone_number = %s", (phone_number,))
    parent = cursor.fetchone()
    
    if parent:
        # Convert tuple to dictionary
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, parent))
    else:
        # New user: create a record
        cursor.execute(
            """
            INSERT INTO parents (full_name, whatsapp_id, phone_number)
            VALUES (%s, %s, %s)
            RETURNING *;
            """,
            (full_name, phone_number, phone_number)
        )
        new_parent = cursor.fetchone()
        columns = [desc[0] for desc in cursor.description]
        logger.info(f"New parent created for phone number: {phone_number}")
        return dict(zip(columns, new_parent))

def get_parent_info(cursor: Psycopg2Cursor, parent_id: int) -> dict:
    """
    Retrieves the parent's data from the database.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
    
    Returns:
        dict: The parent's data as a dictionary.
    """
    cursor.execute("SELECT * FROM parents WHERE id = %s", (parent_id,))
    parent = cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, parent))

def update_current_mode(cursor: Psycopg2Cursor, parent_id: int, mode: str) -> None:
    """
    Updates the parent's current mode in the database.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        mode (str): The new mode.
    """
    cursor.execute(
        """
        UPDATE parents
        SET current_mode = %s
        WHERE id = %s
        """,
        (mode, parent_id)
    )

def update_current_step(cursor: Psycopg2Cursor, parent_id: int, step: str) -> None:
    """
    Updates the parent's current step in the database.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        step (str): The new step.
    """
    cursor.execute(
        """
        UPDATE parents
        SET current_step = %s
        WHERE id = %s
        """,
        (step, parent_id)
    )

def create_appointment(cursor: Psycopg2Cursor, appointment_data: dict) -> dict:
    """
    Creates a new appointment in the database.

    Args:
        cursor (Cursor): The database cursor.
        appointment_data (dict): The appointment data.
    """
    cursor.execute(
        """
        INSERT INTO appointments (parent_id, status, preferred_time_slot, assessment_type, case_notes, urgency_level)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *;
        """,
        (appointment_data["parent_id"], appointment_data["status"], appointment_data["preferred_time_slot"], appointment_data["assessment_type"], appointment_data["case_notes"], appointment_data["urgency_level"])
    )
    new_appointment = cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    logger.info(f"New appointment created for parent {appointment_data['parent_id']}")
    return dict(zip(columns, new_appointment))

def create_coaching_session(cursor: Psycopg2Cursor, coaching_session_data: dict) -> dict:
    """
    Creates a new coaching session in the database.

    Args:
        cursor (Cursor): The database cursor.
        coaching_session_data (dict): The coaching session data.
    """
    cursor.execute(
        """
        INSERT INTO coaching_sessions (parent_id, parent_insight, action_step, follow_up_scheduled, follow_up_sent_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *;
        """,
        (coaching_session_data["parent_id"], coaching_session_data["parent_insight"], coaching_session_data["action_step"], coaching_session_data["follow_up_scheduled"], coaching_session_data["follow_up_sent_at"])
    )
    new_coaching_session = cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    logger.info(f"New coaching session created for parent {coaching_session_data['parent_id']}")
    return dict(zip(columns, new_coaching_session))

def log_escalation(cursor: Psycopg2Cursor, parent_id: int, escalation_details: str) -> None:
    """
    Logs an escalation in the database.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        escalation_details (str): The escalation details.
    """
    cursor.execute(
        """
        INSERT INTO escalations (parent_id, escalation_details)
        VALUES (%s, %s)
        """,
        (parent_id, escalation_details)
    )

def get_message_history(cursor: Psycopg2Cursor, parent_id: int, limit: int = 10) -> str:
    """
    Retrieves the last N messages for a given parent to provide context to the AI.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        limit (int): The number of messages to retrieve.
    
    Returns:
        str: The message history.
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
    # Fetch in descending order, then reverse to get chronological order for the prompt
    history = cursor.fetchall()

    # Convert to string format
    history_str = "\n".join([f"{sender}: {content}" for sender, content in history])
    return history_str

def log_message(cursor: Psycopg2Cursor, parent_id: int, sender: str, content: str) -> None:
    """
    Logs a message to the database.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        sender (str): The sender of the message.
        content (str): The content of the message.
    """
    cursor.execute(
        """
        INSERT INTO messages (parent_id, sender, content)
        VALUES (%s, %s, %s)
        """,
        (parent_id, sender, content)
    )