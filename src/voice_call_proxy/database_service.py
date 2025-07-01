from typing import Dict, Optional, Any

import psycopg2
from psycopg2.extensions import cursor as Psycopg2Cursor
from config import logger, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


def get_db_connection() -> psycopg2.extensions.connection:
    """
    Get reusable database connection for Lambda invocation.
    
    Returns:
        Active PostgreSQL connection
        
    Raises:
        psycopg2.Error: If connection fails
    """
    try:
        db_conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        logger.info("Database connection established")
        return db_conn
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise


def _row_to_dict(cursor: Psycopg2Cursor, row: tuple) -> Dict[str, Any]:
    """Convert database row tuple to dictionary using cursor description."""
    if not row:
        return {}
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


def find_parent_by_whatsapp_id(cursor: Psycopg2Cursor, whatsapp_id: str) -> Optional[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT * FROM parents WHERE whatsapp_id = %s
        """,
        (whatsapp_id,)
    )
    parent = cursor.fetchone()
    if not parent:
        return None
    return _row_to_dict(cursor, parent)


def get_call_history(cursor: Psycopg2Cursor, whatsapp_id: str) -> Optional[str]:
    parent = find_parent_by_whatsapp_id(cursor, whatsapp_id)
    if not parent:
        return None

    cursor.execute(
        """
        SELECT sender, content
        FROM messages
        WHERE parent_id = %s AND message_type = 'call'
        ORDER BY created_at DESC
        LIMIT 100
        """,
        (parent["id"],)
    )
    messages = cursor.fetchall()
    if not messages:
        return None
    return "\n".join([f"{sender}: {content}" for sender, content in messages])


def log_message(cursor: Psycopg2Cursor, whatsapp_id: str, sender: str, content: str, message_type: str = "call") -> None:
    """
    Log message to database.
    
    Args:
        cursor: Database cursor
        whatsapp_id: Parent's ID
        sender: Message sender ('user' or 'ai')
        content: Message content
    """
    parent = find_parent_by_whatsapp_id(cursor, whatsapp_id)
    if not parent:
        raise ValueError(f"Parent with whatsapp_id {whatsapp_id} not found")
    
    parent_id = parent["id"]
    cursor.execute(
        """
        INSERT INTO messages (parent_id, sender, content, message_type)
        VALUES (%s, %s, %s, %s)
        """,
        (parent_id, sender, content, message_type)
    )