import json
import os
import boto3
import logging
import psycopg2
from datetime import datetime, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Environment Variables & Secrets (tương tự ProcessFunction) ---
DB_HOST = os.environ.get('DB_HOST')
DB_PORT = os.environ.get('DB_PORT')
DB_NAME = os.environ.get('DB_NAME')
DB_CREDENTIALS_SECRET_ARN = os.environ.get('DB_CREDENTIALS_SECRET_ARN')
APPLICATION_SECRETS_ARN = os.environ.get('APPLICATION_SECRETS_ARN') # ARN của Secret JSON

secrets_client = boto3.client('secretsmanager')
db_conn = None

def get_secret(secret_arn):
    # (Similar to ProcessFunction)
    try:
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        if 'SecretString' in response:
            return json.loads(response['SecretString'])
        else:
            return json.loads(response['SecretBinary'].decode('utf-8'))
    except Exception as e:
        logger.error(f"Error getting secret {secret_arn}: {e}")
        raise

def load_app_config():
    global app_config
    if app_config is None:
        try:
            logger.info(f"Loading application configuration from Secrets Manager: {APPLICATION_SECRETS_ARN}")
            secret_string = get_secret(APPLICATION_SECRETS_ARN)
            app_config = json.loads(secret_string)
            logger.info("Application configuration loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load application configuration: {e}")
            # Quyết định hành vi khi không load được config (ví dụ: raise error để Lambda fail)
            raise RuntimeError(f"Could not load application configuration from {APPLICATION_SECRETS_ARN}") from e
    return app_config


def get_db_connection():
    # (Similar to ProcessFunction)
    global db_conn
    if db_conn and db_conn.closed == 0:
         try:
            cur = db_conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return db_conn
         except psycopg2.Error:
            logger.info("Database connection was closed or unusable, reconnecting.")
            db_conn = None

    if not db_conn or db_conn.closed != 0:
        try:
            db_creds = get_secret(DB_CREDENTIALS_SECRET_ARN)
            db_conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=db_creds['username'], password=db_creds['password']
            )
            logger.info("Successfully connected to PostgreSQL database for scheduled tasks.")
        except Exception as e:
            logger.error(f"Error connecting to database for scheduled tasks: {e}")
            raise
    return db_conn

def send_wati_message(recipient_id, message_text):
    # (Similar to ProcessFunction, or create a common layer/utility)
    try:
        config = load_app_config()
        wati_api_key = config.get('WATI_API_KEY')
        logger.info(f"Sent WATI message to {recipient_id}: {message_text}")
        print(f"[WATI SIMULATION - SCHEDULED] To {recipient_id}: {message_text}") # Placeholder
        return True
    except Exception as e:
        logger.error(f"Error sending WATI message from scheduled task: {e}")
        return False

def handle_3_day_follow_up():
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
                if send_wati_message(user_id, message_template or "How have things been since we last spoke? Did anything shift, even slightly?"):
                    cur.execute("UPDATE scheduled_follow_ups SET status = 'SENT', sent_at = NOW() WHERE follow_up_id = %s", (follow_up_id,))
                    follow_ups_sent += 1
                else:
                    logger.error(f"Failed to send follow-up message for ID {follow_up_id}")
            conn.commit()
        logger.info(f"Sent {follow_ups_sent} follow-up messages.")
    except Exception as e:
        logger.error(f"Error in handle_3_day_follow_up: {e}", exc_info=True)
        if conn: conn.rollback()


def handle_monthly_summary():
    logger.info("Handling monthly summaries...")
    conn = get_db_connection()
    summaries_sent = 0
    try:
        # Determine previous month
        today = datetime.utcnow()
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


def lambda_handler(event, context):
    logger.info(f"Scheduled task triggered with event: {json.dumps(event)}")
    
    task_type = event.get("task_type")

    if task_type == "3_DAY_FOLLOW_UP":
        handle_3_day_follow_up()
    elif task_type == "MONTHLY_SUMMARY":
        handle_monthly_summary()
    else:
        logger.warning(f"Unknown task type: {task_type}")

    return {
        'statusCode': 200,
        'body': json.dumps({'message': f'Task {task_type} processed.'})
    }