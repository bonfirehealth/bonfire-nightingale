import traceback
from contextlib import contextmanager
from typing import Optional, Tuple, Dict, Any
from psycopg2.extensions import connection as Connection

from config import logger
from message import NUDGE_MESSAGE, MONTHLY_SUMMARY_FALLBACK
from services import database_service as db, wati_service as wati

class NudgeProcessingError(Exception):
    """Custom exception for nudge processing errors"""
    pass


class DatabaseError(Exception):
    """Custom exception for database errors"""
    pass


@contextmanager
def get_db_transaction():
    """Context manager for database transactions with automatic rollback on error"""
    db_conn = None
    try:
        db_conn = db.get_db_connection()
        db_conn.autocommit = False
        yield db_conn
        db_conn.commit()
    except Exception as e:
        if db_conn:
            db_conn.rollback()
        logger.error(f"Database transaction failed: {str(e)}\n{traceback.format_exc()}")
        raise DatabaseError(f"Database transaction failed: {str(e)}") from e
    finally:
        if db_conn:
            try:
                db_conn.close()
            except Exception as e:
                logger.error(f"Error closing database connection: {str(e)}\n{traceback.format_exc()}")


def lambda_handler(event: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main Lambda handler for executing nudge actions with transaction management.

    Args:
        event: The event object containing waId, coachingSessionId, and nudgeType
        context: The context object

    Returns:
        dict: Response with status code and body
    """
    try:
        # Validate required parameters
        whatsapp_id = event.get("waId")
        nudge_type = event.get("nudgeType")
        coaching_session_id = event.get("coachingSessionId")

        if not whatsapp_id or not nudge_type:
            raise ValueError("Missing required parameters: waId and nudgeType are required")

        logger.info(f"Processing nudge {nudge_type} for user {whatsapp_id}")

        with get_db_transaction() as db_conn:
            process_nudge_by_type(db_conn, nudge_type, whatsapp_id, coaching_session_id)

        logger.info(f"Successfully processed nudge {nudge_type} for user {whatsapp_id}")
        return {
            "statusCode": 200,
            "body": "Nudge executed successfully"
        }

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}\n{traceback.format_exc()}")
        return {
            "statusCode": 400,
            "body": f"Validation error: {str(e)}"
        }
    except (DatabaseError, NudgeProcessingError) as e:
        logger.error(f"Processing error: {str(e)}\n{traceback.format_exc()}")
        return {
            "statusCode": 500,
            "body": f"Error processing nudge: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Unexpected error in lambda_handler: {str(e)}\n{traceback.format_exc()}")
        return {
            "statusCode": 500,
            "body": f"Unexpected error: {str(e)}"
        }


def process_nudge_by_type(db_conn: Connection, nudge_type: str, whatsapp_id: str, 
                         coaching_session_id: Optional[int] = None) -> None:
    """
    Process a nudge based on its type using strategy pattern.
    
    Args:
        db_conn: The database connection
        nudge_type: The type of nudge
        whatsapp_id: The WhatsApp ID of the user
        coaching_session_id: The ID of the coaching session (optional)
    """
    nudge_processors = {
        "3_day_follow_up": lambda: process_3_day_follow_up(db_conn, whatsapp_id, coaching_session_id),
        "monthly_summary": lambda: process_monthly_summary(db_conn, whatsapp_id),
        "trial_expiry": lambda: process_trial_expiry(db_conn, whatsapp_id),
    }
    
    try:
        # Handle specific nudge types
        if nudge_type in nudge_processors:
            nudge_processors[nudge_type]()
        else:
            raise NudgeProcessingError(f"Unknown nudge type: {nudge_type}")
            
    except Exception as e:
        logger.error(f"Error processing nudge {nudge_type} for user {whatsapp_id}: {str(e)}\n{traceback.format_exc()}")
        raise NudgeProcessingError(f"Failed to process nudge {nudge_type}") from e


def process_3_day_follow_up(db_conn: Connection, whatsapp_id: str, coaching_session_id: Optional[int]) -> None:
    """
    Process a 3-day follow-up nudge for a user.
    
    Args:
        db_conn: The database connection
        whatsapp_id: The WhatsApp ID of the user
        coaching_session_id: The ID of the coaching session
    """
    if not coaching_session_id:
        raise ValueError("coaching_session_id is required for 3-day follow-up")
    
    try:
        message = NUDGE_MESSAGE.get("3_day_follow_up")
        if not message:
            raise NudgeProcessingError("No message defined for 3-day follow-up")

        # Update database
        with db_conn.cursor() as cursor:
            cursor.execute(
                "UPDATE coaching_sessions SET follow_up_sent_at = CURRENT_TIMESTAMP WHERE id = %s",
                (coaching_session_id,)
            )
            
            if cursor.rowcount == 0:
                raise NudgeProcessingError(f"No coaching session found with ID {coaching_session_id}")

        # Send message
        wati.send_message(whatsapp_id, message)

        # Log message
        parent_id = _get_parent_id_from_whatsapp_id(db_conn, whatsapp_id)
        _log_message(db_conn, parent_id, "ai", message)
        logger.info(f"3-day follow-up processed successfully for user {whatsapp_id}")

    except Exception as e:
        logger.error(f"Error processing 3-day follow-up for user {whatsapp_id}: {str(e)}\n{traceback.format_exc()}")
        raise


def process_monthly_summary(db_conn: Connection, whatsapp_id: str) -> None:
    """
    Process a monthly summary nudge for a user.
    
    Args:
        db_conn: The database connection
        whatsapp_id: The WhatsApp ID of the user
    """
    try:
        # Check if we can send the monthly summary
        if not _can_send_monthly_summary(db_conn, whatsapp_id):
            logger.info(f"Monthly summary already sent for user {whatsapp_id}")
            return

        # Get monthly summary data
        monthly_stats = _get_monthly_summary_data(db_conn, whatsapp_id)
        if not monthly_stats:
            logger.error(f"No monthly summary data found for user {whatsapp_id}")
            return

        # Update sent timestamp
        _update_monthly_summary_sent(db_conn, whatsapp_id)

        # Send message
        message = _build_monthly_summary_message(monthly_stats)
        wati.send_message(whatsapp_id, message)

        # Log message
        parent_id = _get_parent_id_from_whatsapp_id(db_conn, whatsapp_id)
        _log_message(db_conn, parent_id, "ai", message)
        
        logger.info(f"Monthly summary processed successfully for user {whatsapp_id}")

    except Exception as e:
        logger.error(f"Error processing monthly summary for user {whatsapp_id}: {str(e)}\n{traceback.format_exc()}")
        raise


def process_trial_expiry(db_conn: Connection, whatsapp_id: str) -> None:
    """
    Process trial expiry for a user.
    
    Args:
        db_conn: The database connection
        whatsapp_id: The WhatsApp ID of the user
    """
    try:
        # Check if we can send the nudge
        if not _can_send_nudge(db_conn, whatsapp_id, "trial_expiry"):
            logger.info(f"Trial expiry nudge already processed for user {whatsapp_id}")
            return

        # Update subscription status
        with db_conn.cursor() as cursor:
            cursor.execute(
                "UPDATE parents SET subscription_status = 'trial_expired' WHERE whatsapp_id = %s AND subscription_status = 'trialing'",
                (whatsapp_id,)
            )
            
            if cursor.rowcount == 0:
                logger.warning(f"No trialing user found for WhatsApp ID {whatsapp_id}")
            else:
                logger.info(f"Updated subscription status to trial_expired for user {whatsapp_id}")
        
        # Send message
        message = NUDGE_MESSAGE.get("trial_expiry")
        if not message:
            raise NudgeProcessingError("No message defined for trial expiry")

        wati.send_message(whatsapp_id, message)

    except Exception as e:
        logger.error(f"Error processing trial expiry for user {whatsapp_id}: {str(e)}\n{traceback.format_exc()}")
        raise


# Helper functions
def _can_send_monthly_summary(db_conn: Connection, whatsapp_id: str) -> bool:
    """Check if monthly summary can be sent to user"""
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT can_send_monthly_summary_to_user(%s)", (whatsapp_id,))
        result = cursor.fetchone()
        return result[0] if result else False


def _can_send_nudge(db_conn: Connection, whatsapp_id: str, nudge_type: str) -> bool:
    """Check if nudge can be sent to user"""
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT can_send_nudge_to_user(%s, %s)", (whatsapp_id, nudge_type))
        result = cursor.fetchone()
        return result[0] if result else False


def _get_monthly_summary_data(db_conn: Connection, whatsapp_id: str) -> Optional[Tuple]:
    """Get monthly summary data for user"""
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT create_monthly_summary_for_user(%s)", (whatsapp_id,))
        return cursor.fetchone()


def _update_monthly_summary_sent(db_conn: Connection, whatsapp_id: str) -> None:
    """Update monthly summary sent timestamp"""
    with db_conn.cursor() as cursor:
        cursor.execute(
            "UPDATE parents SET monthly_summary_sent_at = CURRENT_TIMESTAMP WHERE whatsapp_id = %s",
            (whatsapp_id,)
        )
        if cursor.rowcount == 0:
            raise NudgeProcessingError(f"No parent found for WhatsApp ID {whatsapp_id}")


def _build_monthly_summary_message(monthly_stats: Tuple) -> str:
    """Build monthly summary message from stats"""
    if not monthly_stats or monthly_stats[0] is None:
        raise NudgeProcessingError("Invalid monthly summary data")
    
    base_message = NUDGE_MESSAGE.get("monthly_summary", MONTHLY_SUMMARY_FALLBACK)
    return base_message.format(
        full_name=monthly_stats[0],
        successful_follow_ups=monthly_stats[1],
        total_sessions=monthly_stats[2]
    )


def _is_valid_whatsapp_id(whatsapp_id: str) -> bool:
    """Check if the WhatsApp ID is valid"""
    return isinstance(whatsapp_id, str) and whatsapp_id.isdigit() and len(whatsapp_id) > 0

def _get_parent_id_from_whatsapp_id(db_conn: Connection, whatsapp_id: str) -> int:
    """
    Get parent ID from coaching session ID.
    
    Args:
        db_conn: The database connection
        whatsapp_id: WhatsApp ID of the user
        
    Returns:
        Parent ID
    """
    if not _is_valid_whatsapp_id(whatsapp_id):
        raise ValueError(f"Invalid WhatsApp ID: {whatsapp_id}")

    if not db_conn:
        raise ValueError("Database connection is required to get parent ID")

    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM parents WHERE whatsapp_id = %s",
            (whatsapp_id,)
        )
        result = cursor.fetchone()
        if result is None:
            raise NudgeProcessingError(f"No coaching session found with ID {whatsapp_id}")
        return result[0]

def _log_message(db_conn: Connection, parent_id: int, sender: str, content: str) -> None:

    """
    Logs a message to the database.
    
    Args:
        db_conn: The database connection
        parent_id: Parent's ID
        sender: Message sender ('user' or 'ai')
        content: Message content
    """
    if not db_conn:
        raise ValueError("Database connection is required to log messages")
    
    if not isinstance(parent_id, int) or parent_id <= 0:
        raise ValueError(f"Invalid parent ID: {parent_id}")
    
    if sender not in ["user", "ai"]:
        raise ValueError(f"Invalid sender type: {sender}. Must be 'user' or 'ai'.")

    with db_conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO messages (parent_id, sender, content) VALUES (%s, %s, %s)",
            (parent_id, sender, content)
        )