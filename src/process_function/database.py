import os
import json
import logging
from datetime import datetime, timezone, timedelta

import psycopg2
from config import get_secret

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DB_HOST = os.environ.get('DB_HOST')
DB_PORT = os.environ.get('DB_PORT')
DB_NAME = os.environ.get('DB_NAME')
DB_CREDENTIALS_SECRET_ARN = os.environ.get('DB_CREDENTIALS_SECRET_ARN')

# --- Database Connection ---
def get_db_connection() -> psycopg2.extensions.connection:
    db_conn = None
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

def get_or_create_user(conn, user_id: str, user_name: str = None) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, name, is_wtw_employee, wtw_handbook_sent_at FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if user:
            logger.info(f"User {user_id} found.")
            return {"user_id": user[0], "name": user[1], "is_wtw_employee": user[2], "wtw_handbook_sent_at": user[3]}
        else:
            # Giả sử WTW employee status được xác định sau, hoặc từ message đầu tiên
            cur.execute(
                "INSERT INTO users (user_id, name) VALUES (%s, %s) RETURNING user_id, name, is_wtw_employee, wtw_handbook_sent_at",
                (user_id, user_name)
            )
            new_user = cur.fetchone()
            conn.commit()
            logger.info(f"User {user_id} created.")
            return {"user_id": new_user[0], "name": new_user[1], "is_wtw_employee": new_user[2], "wtw_handbook_sent_at": new_user[3]}

def get_active_conversation_state(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT conversation_id, openai_thread_id, current_sst_step, conversation_state_json
            FROM conversations
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY last_interaction_at DESC
            LIMIT 1
        """, (user_id,))
        convo = cur.fetchone()
        if convo:
            logger.info(f"Active conversation found for {user_id}: ID {convo[0]}, Thread ID {convo[1]}")
            return {
                "conversation_id": convo[0],
                "openai_thread_id": convo[1],
                "current_sst_step": convo[2],
                "state_json": convo[3] or {}
            }
    logger.info(f"No active conversation found for {user_id}.")
    return None

def create_new_conversation(conn, user_id, initial_step="INIT", initial_state_json=None):
    if initial_state_json is None:
        initial_state_json = {} # Không cần history nữa nếu dùng Threads API
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO conversations (user_id, current_sst_step, conversation_state_json)
            VALUES (%s, %s, %s)
            RETURNING conversation_id, openai_thread_id, current_sst_step, conversation_state_json
        """, (user_id, initial_step, json.dumps(initial_state_json)))
        new_convo = cur.fetchone()
        conn.commit()
        logger.info(f"New conversation created for {user_id}: ID {new_convo[0]}")
        return {
            "conversation_id": new_convo[0],
            "openai_thread_id": new_convo[1],
            "current_sst_step": new_convo[2],
            "state_json": new_convo[3]
        }

def update_conversation_with_thread_id(conn, conversation_id, openai_thread_id):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE conversations
            SET openai_thread_id = %s, updated_at = NOW()
            WHERE conversation_id = %s
        """, (openai_thread_id, conversation_id))
        conn.commit()
        logger.info(f"Updated conversation {conversation_id} with OpenAI Thread ID: {openai_thread_id}")

def update_conversation_state(conn, conversation_id: int, next_sst_step: str, new_state_json: dict, is_active: bool = True) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE conversations
            SET current_sst_step = %s, conversation_state_json = %s, last_interaction_at = NOW(), is_active = %s
            WHERE conversation_id = %s
        """, (next_sst_step, json.dumps(new_state_json), is_active, conversation_id))
        conn.commit()
        logger.info(f"Conversation {conversation_id} updated. Next step: {next_sst_step}, Active: {is_active}")

def save_session_outcome(conn, conversation_id: int, user_id: str, insight: str, action_step: str) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO session_outcomes (conversation_id, user_id, insight_text, action_step_text)
            VALUES (%s, %s, %s, %s) RETURNING outcome_id
        """, (conversation_id, user_id, insight, action_step))
        outcome_id = cur.fetchone()[0]
        conn.commit()
        logger.info(f"Session outcome saved for conversation {conversation_id}, outcome_id: {outcome_id}")
        return outcome_id

def schedule_follow_up_db(conn, user_id: str, outcome_id: int, schedule_in_days: int, message_template: str) -> None:
    scheduled_time = datetime.now(timezone.utc) + timedelta(days=schedule_in_days)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scheduled_follow_ups (user_id, outcome_id, scheduled_time, follow_up_message_template, status)
            VALUES (%s, %s, %s, %s, 'PENDING')
        """, (user_id, outcome_id, scheduled_time, message_template))
        conn.commit()
        logger.info(f"Follow-up scheduled for user {user_id} at {scheduled_time}")

def log_progress_db(conn, user_id: str, action_taken: str, reported_outcome: str = None, outcome_id: int = None) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO progress_tracking (user_id, outcome_id, action_taken, reported_outcome)
            VALUES (%s, %s, %s, %s)
        """,(user_id, outcome_id, action_taken, reported_outcome))
        conn.commit()
        logger.info(f"Progress logged for user {user_id}: {action_taken}")
