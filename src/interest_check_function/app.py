# lambda_fns/interest_check_lambda/app.py
import json
import os
import boto3
import logging
import psycopg2
from datetime import datetime, timedelta, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Config & DB (similar to process_function) ---
DB_HOST = os.environ.get('DB_HOST')
DB_PORT = os.environ.get('DB_PORT')

# Placeholder for shared database functions - ideally, you'd have a common DB layer
def get_secret_value_placeholder(secret_arn): # Replace with actual
    # ...
    pass
def get_db_connection_placeholder(): # Replace with actual
    # ...
    pass

def find_users_for_interest_check(conn):
    users_to_check = []
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)

    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        # Example Query: Users who started concierge, have some data, but not confirmed/paid,
        # and haven't been contacted for interest check recently.
        # This query needs significant refinement based on your exact criteria.
        cur.execute("""
            SELECT DISTINCT c.user_id, u.name as user_name
            FROM conversations c
            JOIN users u ON c.user_id = u.user_id
            JOIN appointments a ON c.conversation_id = a.conversation_id
            WHERE c.current_mode = 'CONCIERGE'
              AND a.status IN ('PENDING_INFORMATION', 'INFORMATION_COLLECTED') 
              AND a.updated_at BETWEEN %s AND %s -- Showed activity 3-7 days ago
              AND NOT EXISTS (
                  SELECT 1 FROM scheduled_follow_ups sf
                  WHERE sf.user_id = c.user_id
                    AND sf.purpose = 'INTEREST_CHECK_CALL'
                    AND sf.created_at > %s -- Not checked in last 7 days
              )
              -- AND c.user_id NOT IN (SELECT user_id FROM users WHERE keith_call_declined_recently = TRUE) -- Add more flags
        """, (seven_days_ago, three_days_ago, seven_days_ago))
        users_to_check = cur.fetchall()
    logger.info(f"Found {len(users_to_check)} users for interest check.")
    return users_to_check

def schedule_interest_check_call_offer(conn, user_id, user_name=None):
    purpose = 'INTEREST_CHECK_CALL'
    # Schedule it to be sent soon (e.g., by the main ScheduledTasksFunction)
    # Or this Lambda could send it directly if it has WATI access.
    # For now, let's assume it schedules for the other Lambda.
    scheduled_time = datetime.now(timezone.utc) + timedelta(minutes=5) # Send soon
    
    name_to_use = user_name if user_name else "there"
    message_template = (
        f"Hi {name_to_use}, this is Nightingale from Bonfire Pediatrics. "
        "I noticed you were looking into our assessment services recently. "
        "If you're still considering, would you be open to a brief, no-obligation call with Keith, our Clinic Director? "
        "He'd be happy to answer any questions you might have. No pressure at all! "
        "Just reply 'YES KEITH CALL' if interested."
    )
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scheduled_follow_ups (user_id, scheduled_time, follow_up_message_template, purpose, status)
            VALUES (%s, %s, %s, %s, 'PENDING')
            ON CONFLICT (user_id, purpose) WHERE status = 'PENDING' -- Avoid duplicate pending checks
            DO NOTHING; 
        """, (user_id, scheduled_time, message_template, purpose))
        if cur.rowcount > 0:
            conn.commit()
            logger.info(f"Scheduled interest check call offer for user {user_id}")
            return True
        else:
            logger.info(f"Interest check call offer already pending for user {user_id} or conflict occurred.")
            return False


def lambda_handler(event, context):
    logger.info("InterestCheckLambda started.")
    # conn = get_db_connection_placeholder() # Implement this
    # if not conn:
    #     logger.error("Failed to connect to database.")
    #     return {"status": "error", "message": "DB connection failed"}

    # try:
    #     users = find_users_for_interest_check(conn)
    #     scheduled_count = 0
    #     for user_record in users:
    #         if schedule_interest_check_call_offer(conn, user_record['user_id'], user_record.get('user_name')):
    #             scheduled_count += 1
        
    #     logger.info(f"InterestCheckLambda finished. Scheduled offers for {scheduled_count} users.")
    #     return {"status": "success", "scheduled_count": scheduled_count}
    # except Exception as e:
    #     logger.error(f"Error in InterestCheckLambda: {e}", exc_info=True)
    #     # if conn: conn.rollback() # Rollback on error
    #     return {"status": "error", "message": str(e)}
    # finally:
    #     # if conn and not conn.closed:
    #     #     conn.close()
    #     pass
    logger.warning("InterestCheckLambda is currently a stub. Implement DB connection and logic.")
    return {"status": "stub_executed"}