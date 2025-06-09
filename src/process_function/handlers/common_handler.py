import psycopg2

from config import logger

def handle_initial_greeting(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Send initial greeting message

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    with db_conn.cursor() as cursor:
        # Update parent name, whatsapp_id if available
        data = ai_json["data"]
        if "parent_name" in data:
            cursor.execute("UPDATE users SET name = %s WHERE id = %s", (data["parent_name"], user_id))
        if "parent_whatsapp_id" in data:
            cursor.execute("UPDATE users SET whatsapp_id = %s WHERE id = %s", (data["parent_whatsapp_id"], user_id))
    db_conn.commit()

def handle_general_action(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Send general purpose message

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    with db_conn.cursor() as cursor:
        # Update parent name, whatsapp_id if available
        data = ai_json.get("data", {})

        if "mode" in data:
            cursor.execute("UPDATE conversations SET mode = %s WHERE id = %s", (data["mode"], conversation_id))

        if "parent_name" in data:
            cursor.execute("UPDATE users SET name = %s WHERE id = %s", (data["parent_name"], user_id))
        if "parent_whatsapp_id" in data:
            cursor.execute("UPDATE users SET whatsapp_id = %s WHERE id = %s", (data["parent_whatsapp_id"], user_id))
        
        # Update child name, age if available
        if "child_name" in data:
            cursor.execute("UPDATE children SET name = %s WHERE parent_id = %s", (data["child_name"], user_id))
        if "child_age" in data:
            cursor.execute("UPDATE children SET age = %s WHERE parent_id = %s", (data["child_age"], user_id))
    db_conn.commit()

def handle_switch_to_coaching(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Update session mode to coaching, increment session count

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE conversations SET mode = 'coaching' WHERE id = %s", (conversation_id,))
        cursor.execute("UPDATE users SET coaching_session_count = coaching_session_count + 1 WHERE id = %s", (conversation_id,))
    db_conn.commit()

def handle_switch_to_concierge(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Update session mode to concierge, create booking record

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE conversations SET mode = 'concierge' WHERE id = %s", (conversation_id,))
    db_conn.commit()
