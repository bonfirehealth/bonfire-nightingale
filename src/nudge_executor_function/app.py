from config import logger
from services import database_service as db
from services import wati_service as wati

def lambda_handler(event: dict, context: dict) -> dict:
    """
    Main Lambda handler for executing nudge actions.

    Args:
        event (dict): The event object.
        context (dict): The context object.
    """
    whatsapp_id = event.get("waId")
    coaching_session_id = event.get("coachingSessionId")
    nudge_type = event.get("nudgeType") # e.g., "day_7", "day_14", "trial_expiry"

    db_conn = db.get_db_connection()
    if nudge_type == "3_day_follow_up":
        logger.info(f"Executing 3-day follow-up for user {whatsapp_id}")
        
        message = "How have things been since we last spoke? Did anything shift, even slightly?"
        
        # Send message to parent
        wati.send_message(whatsapp_id, message)
        
        # Log the message to the database
        if coaching_session_id:
            with db_conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE coaching_sessions SET follow_up_sent_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (coaching_session_id,)
                )

                # Save the message to the database
                parent_id = db.get_parent_id_from_coaching_session_id(cursor, coaching_session_id)
                db.log_message(cursor, parent_id, 'ai', message)
            db_conn.commit()
        
        logger.info(f"Sent 3-day follow-up to user {whatsapp_id}")
    elif nudge_type.startswith("nudge_day_") or nudge_type == "trial_expiry":
        nudge_day = int(nudge_type.split('_')[2]) if nudge_type.startswith("nudge_day_") else 30
        # 1. Check if the last nudge was sent in the database
        with db_conn.cursor() as cursor:
            cursor.execute("SELECT can_send_nudge_to_user(%s, %s);", (whatsapp_id, nudge_day))
            can_send = cursor.fetchone()[0]

        if not can_send:
            logger.info(f"Skipping nudge {nudge_type} for user {whatsapp_id}. Condition not met.")
            return

        # 2. Handle the nudge type
        if nudge_type == "trial_expiry":
            with db_conn.cursor() as cursor:
                cursor.execute("UPDATE users SET subscription_status = 'trial_expired' WHERE id = %s", (whatsapp_id,))
            db_conn.commit()
            logger.info(f"Trial expired for user {whatsapp_id}.")
            # TODO: Send a message "Your trial has ended"
        else:
            # Get the message content
            message = get_nudge_message(nudge_type)

            # Send message to parent
            wati.send_message(whatsapp_id, message)

            # Log the message to the database
            with db_conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO trial_nudges (user_id, nudge_day) VALUES (%s, %s)",
                    (whatsapp_id, nudge_day)
                )
            db_conn.commit()
            logger.info(f"Sent nudge {nudge_type} to user {whatsapp_id}.")
    
    return {
        "statusCode": 200,
        "body": "Nudge executed successfully"
    }

def get_nudge_message(nudge_type: str) -> str:
    """
    Get the message content for a given nudge type.

    Args:
        nudge_type (str): The type of nudge.
    """
    messages = {
        "day_7": "Hi, It's been 7 days since you started... Do you want to try another coaching session?",
        "day_14": "Hi, It's been 14 days since you started... Do you want to try another coaching session?",
        "day_28": "Hi, It's been 28 days since you started... Do you want to try another coaching session?"
    }
    return messages.get(nudge_type, "")