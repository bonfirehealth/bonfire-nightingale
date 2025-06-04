import logging
from datetime import datetime, timedelta

import pytz

from wati_service import send_wati_message
from database import get_db_connection

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handle_3_day_follow_up() -> None:
    logger.info("Handling 3-day follow-ups...")
    conn = get_db_connection()
    follow_ups_sent = 0
    try:
        with conn.cursor() as cur:
            # Get all PENDING follow-ups where scheduled_time has passed
            cur.execute("""
                SELECT follow_up_id, user_id, follow_up_message_template
                FROM scheduled_follow_ups
                WHERE status = 'PENDING' AND scheduled_time <= NOW()
            """)
            pending_follow_ups = cur.fetchall()

            for follow_up_id, user_id, message_template in pending_follow_ups:
                logger.info(f"Processing follow-up ID {follow_up_id} for user {user_id}")
                default_message_template = "How have things been since we last spoke? Did anything shift, even slightly?"
                if send_wati_message(user_id, message_template or default_message_template):
                    cur.execute("UPDATE scheduled_follow_ups SET status = 'SENT', sent_at = NOW() WHERE follow_up_id = %s", (follow_up_id,))
                    follow_ups_sent += 1
                else:
                    logger.error(f"Failed to send follow-up message for ID {follow_up_id}")
            conn.commit()
        logger.info(f"Sent {follow_ups_sent} follow-up messages.")
    except Exception as e:
        logger.error(f"Error in handle_3_day_follow_up: {e}", exc_info=True)
        if conn: conn.rollback()

def handle_monthly_summary() -> None:
    logger.info("Handling monthly summaries...")
    conn = get_db_connection()
    summaries_sent = 0
    try:
        # Determine previous month
        today = datetime.now(pytz.utc)
        first_day_of_current_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
        first_day_of_previous_month = last_day_of_previous_month.replace(day=1)

        with conn.cursor() as cur:
            # Get user_id of those who have activity in the previous month
            cur.execute("""
                SELECT DISTINCT user_id
                FROM progress_tracking
                WHERE timestamp >= %s AND timestamp < %s
            """, (first_day_of_previous_month, first_day_of_current_month))
            active_users = cur.fetchall()

            for (user_id,) in active_users:
                # Count total steps and successful steps (need to define 'success')
                # Example: reported_outcome contains positive keywords
                cur.execute("""
                    SELECT
                        COUNT(*) as total_steps,
                        SUM(CASE WHEN reported_outcome ILIKE '%%helped%%' OR reported_outcome ILIKE '%%positive%%' THEN 1 ELSE 0 END) as successful_steps
                    FROM progress_tracking
                    WHERE user_id = %s AND timestamp >= %s AND timestamp < %s
                """, (user_id, first_day_of_previous_month, first_day_of_current_month))
                progress_data = cur.fetchone()
                
                if progress_data and progress_data[0] > 0: # total_steps
                    total_steps = progress_data[0]
                    successful_steps = progress_data[1] if progress_data[1] else 0
                    
                    summary_message = f"Over the past month, you’ve tried {total_steps} small steps. {successful_steps} of them helped. Want to adjust your plan together?"
                    if send_wati_message(user_id, summary_message):
                        # Log sent summary (optional)
                        summaries_sent += 1
                        logger.info(f"Sent monthly summary to user {user_id}")
                    else:
                        logger.error(f"Failed to send monthly summary to user {user_id}")
        logger.info(f"Sent {summaries_sent} monthly summaries.")
    except Exception as e:
        logger.error(f"Error in handle_monthly_summary: {e}", exc_info=True)
        if conn: conn.rollback()


