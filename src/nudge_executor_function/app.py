from config import logger
from services import database_service as db
from services import wati_service as wati

def lambda_handler(event: dict, context: dict) -> dict:
    """
    Main Lambda handler for executing nudge actions with transaction management and rollback.

    Args:
        event (dict): The event object.
        context (dict): The context object.

    Returns:
        dict: Response with status code and body.
    """
    whatsapp_id = event.get("waId")
    coaching_session_id = event.get("coachingSessionId")
    nudge_type = event.get("nudgeType")  # e.g., "day_7", "day_14", "trial_expiry"

    db_conn = None
    try:
        db_conn = db.get_db_connection()
        db_conn.autocommit = False  # Enable transaction management

        if nudge_type == "3_day_follow_up":
            logger.info(f"Executing 3-day follow-up for user {whatsapp_id}")
            
            message = "Hey! How have things been since we last spoke? Did anything shift, even slightly?"
            
            # Send message to parent
            wati.send_message(whatsapp_id, message)
            
            if coaching_session_id:
                with db_conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE coaching_sessions SET follow_up_sent_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (coaching_session_id,)
                    )

                    # Save the message to the database
                    parent_id = db.get_parent_id_from_coaching_session_id(cursor, coaching_session_id)
                    db.log_message(cursor, parent_id, 'ai', message)
                    logger.info(f"Logged 3-day follow-up message for user {whatsapp_id}")
                
                db_conn.commit()
            
            logger.info(f"Sent 3-day follow-up to user {whatsapp_id}")
        
        elif nudge_type == "monthly_summary":
            logger.info(f"Executing monthly summary for user {whatsapp_id}")

            # Get monthly report
            with db_conn.cursor() as cursor:
                cursor.execute("SELECT create_monthly_report(%s);", (whatsapp_id,))
                monthly_report = cursor.fetchone()
                
                if monthly_report:
                    message = monthly_report[0]
                    wati.send_message(whatsapp_id, message)
                    logger.info(f"Sent monthly summary to user {whatsapp_id}")
                else:
                    logger.info(f"No monthly report found for user {whatsapp_id}")

            # Update parent info
            with db_conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE parents SET monthly_summary_sent_at = CURRENT_TIMESTAMP WHERE whatsapp_id = %s",
                    (whatsapp_id,)
                )
                db_conn.commit()
                logger.info(f"Updated monthly summary sent at for user {whatsapp_id}")

        elif nudge_type.startswith("nudge_day_") or nudge_type == "trial_expiry":
            try:
                # Start transaction
                with db_conn.cursor() as cursor:
                    # 1. Check if we can send the nudge
                    cursor.execute("SELECT can_send_nudge_to_user(%s, %s);", (whatsapp_id, nudge_type))
                    can_send = cursor.fetchone()[0]

                if not can_send:
                    logger.info(f"Skipping nudge {nudge_type} for user {whatsapp_id}. Condition not met.")
                    db_conn.rollback()
                    return {"statusCode": 200, "body": "Nudge condition not met"}

                # 2. Get the message content
                message = get_nudge_message(nudge_type)
                if not message:
                    logger.error(f"No message defined for nudge type: {nudge_type}")
                    db_conn.rollback()
                    return {"statusCode": 400, "body": f"No message defined for nudge type: {nudge_type}"}

                # 3. Send message to parent
                wati.send_message(whatsapp_id, message)

                # 4. Update database
                set_clause = ""
                if nudge_type == "nudge_day_7_soft_introduction":
                    set_clause = "sent_nudge_day_7_soft_introduction = TRUE"

                elif nudge_type == "nudge_day_14_low_usage":
                    set_clause = "sent_nudge_day_14_low_usage = TRUE"

                elif nudge_type == "nudge_day_20_conversion":
                    set_clause = "sent_nudge_day_20_conversion = TRUE"

                elif nudge_type == "nudge_day_28_final_reminder":
                    set_clause = "sent_nudge_day_28_final_reminder = TRUE"

                elif nudge_type == "trial_expiry":
                    set_clause = "subscription_status = 'trial_expired'"

                else:
                    logger.info(f"Skipping nudge {nudge_type} for user {whatsapp_id}. Condition not met.")
                    db_conn.rollback()
                    return {"statusCode": 200, "body": "Nudge condition not met"}

                with db_conn.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE parents SET {set_clause} WHERE whatsapp_id = %s",
                        (whatsapp_id,)
                    )
                
                # Log the message to the database
                db.log_message(cursor, parent_id, 'ai', message)
                logger.info(f"Logged nudge {nudge_type} for user {whatsapp_id}")

                # If we get here, commit all changes
                db_conn.commit()
                logger.info(f"Successfully sent nudge {nudge_type} to user {whatsapp_id}.")

            except Exception as e:
                db_conn.rollback()
                logger.error(f"Error processing nudge {nudge_type} for user {whatsapp_id}: {str(e)}")
                raise

        return {
            "statusCode": 200,
            "body": "Nudge executed successfully"
        }

    except Exception as e:
        logger.error(f"Unexpected error in lambda_handler: {str(e)}")
        if db_conn:
            db_conn.rollback()
        return {
            "statusCode": 500,
            "body": f"Error processing nudge: {str(e)}"
        }
    finally:
        if db_conn:
            try:
                db_conn.close()
            except Exception as e:
                logger.error(f"Error closing database connection: {str(e)}")

def get_nudge_message(nudge_type: str) -> str:
    """
    Get the message content for a given nudge type.

    Args:
        nudge_type (str): The type of nudge.
    """
    messages = {
        "nudge_day_7_soft_introduction": "Hello! This is Nightingale again, your AI Parenting Coach from Bonfire Pediatrics. Just checking in — did you manage to apply anything from the parent guidebook last week? I'm here if you want to talk through anything — whether it's a tough moment with your child, questions about confusing behaviors, or just figuring out how to parent better. What has bothered you in the past week?",
        "nudge_day_14_low_usage": "Hello! This is Nightingale again, your AI Parenting Coach from Bonfire Pediatrics. Just checking in — it's been a couple of weeks since you got our parent guidebook, and I wanted to see how things have been going. If anything's been weighing on you lately — whether it's stress at home, a tough moment with your child, or something you've been second-guessing. What has bothered you in the past week?",
        "nudge_day_20_conversion": "You've already started making great progress. Here's a summary of your achievements: [Summary of past sessions]. Nightingale's here to keep supporting you beyond this free trial. Would you like us to continue this support for just $8/month? If yes, please reply with 'Yes'.",
        "nudge_day_28_reminder": "Hi again! Your Nightingale free trial ends in two days. I'd love to keep supporting you if you'd like to stay on — it's just $8/month, and you can cancel anytime. If you're keen to continue, please reply with 'Yes' to receive the payment link. Do you need help with the payment process?",
        "trial_expiry": "Hi, your trial has ended. If you'd like to continue using Nightingale, please reply with 'Yes' to receive the payment link."
    }
    return messages.get(nudge_type, "")