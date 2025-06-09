import psycopg2

import utils
from config import logger

def handle_start_sst_framework(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Create new coaching session record.

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("INSERT INTO coaching_sessions (conversation_id, status) VALUES (%s, 'active')", (conversation_id,))
    db_conn.commit()

def handle_coaching_session_complete(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Update coaching session result, increase counter, and activate trial
    if this is the first session.

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    try:
        with db_conn.cursor() as cursor:
            # Get the current status of the user to make a decision
            cursor.execute("SELECT subscription_status, coaching_session_count FROM users WHERE id = %s FOR UPDATE", (user_id,))
            result = cursor.fetchone()
            if not result:
                logger.error(f"User with id {user_id} not found.")
                return

            subscription_status, current_session_count = result

            if subscription_status == "pre_trial":
                logger.info(f"User {user_id} is completing their first session. Activating trial.")
                # This is the first session -> Activate trial
                cursor.execute("""
                UPDATE users 
                SET subscription_status = 'trialing', 
                    trial_start_date = CURRENT_TIMESTAMP,
                    last_coaching_date = CURRENT_TIMESTAMP,
                    coaching_session_count = 1
                WHERE id = %s
                """, (user_id,))

                # === IMPORTANT: CALL THE SCHEDULES CREATION FUNCTION ===
                utils.create_trial_schedules(user_id)

            elif subscription_status in ("trialing", "converted_paid"):
                logger.info(f"User {user_id} is completing another session.")
                # This is not the first session -> Update only
                cursor.execute("""
                UPDATE users 
                SET last_coaching_date = CURRENT_TIMESTAMP,
                    coaching_session_count = coaching_session_count + 1
                WHERE id = %s
                """, (user_id,))
            
            # Update the coaching_session information
            cursor.execute("""
            UPDATE coaching_sessions 
            SET status = 'completed', 
                completed_at = CURRENT_TIMESTAMP,
                parent_insight = %s,
                micro_step = %s,
                follow_up_scheduled = %s,
                follow_up_date = CASE WHEN %s = true THEN created_at + INTERVAL '3 days' ELSE follow_up_date END
            WHERE conversation_id = %s AND status = 'active'
            """, (
                ai_json["data"].get("parent_insight"),
                ai_json["data"].get("micro_step"),
                ai_json["data"].get("follow_up_scheduled", False),
                ai_json["data"].get("follow_up_scheduled", False),
                conversation_id
            ))

            follow_up_needed = ai_json["data"].get("follow_up_scheduled", False)

            if follow_up_needed:
                logger.info(f"Scheduling a 3-day follow-up for user {user_id}.")
                
                # We need a function similar to create_trial_schedules
                # but only to create a single schedule.
                # This function can be called from many places so let's separate it.
                try:
                    utils.schedule_single_event(
                        user_id=user_id,
                        conversation_id=conversation_id, # Pass conversation_id to have context
                        event_type="3_day_follow_up",
                        days_from_now=3
                    )
                except Exception as e:
                    # Handle error if the schedule creation fails
                    # We can log the error but don't need to rollback the entire transaction
                    # because the follow-up is not as important as activating the trial.
                    logger.error(f"Failed to schedule 3-day follow-up for user {user_id}. Error: {e}")
        
        # If everything is successful (including schedule creation), commit transaction
        db_conn.commit()
        logger.info(f"Successfully processed completed session for user {user_id}")

    except Exception as e:
        # If any error occurs (DB error or schedule creation error)
        # rollback all changes in DB to ensure consistency.
        logger.error(f"An error occurred in handle_coaching_session_complete for user {user_id}. Rolling back. Error: {e}")
        db_conn.rollback()
