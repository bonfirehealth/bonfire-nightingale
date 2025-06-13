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

def get_parent_id_from_coaching_session_id(cursor: Psycopg2Cursor, coaching_session_id: int) -> int:
    """
    Get parent ID from coaching session ID.
    
    Args:
        cursor: Database cursor
        coaching_session_id: Coaching session ID
        
    Returns:
        Parent ID
    """
    cursor.execute(
        """
        SELECT parent_id FROM coaching_sessions WHERE id = %s
        """,
        (coaching_session_id,)
    )
    result = cursor.fetchone()
    return result[0] if result else None

def log_message(cursor: Psycopg2Cursor, parent_id: int, sender: str, content: str) -> None:
    """
    Logs a message to the database.
    
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
