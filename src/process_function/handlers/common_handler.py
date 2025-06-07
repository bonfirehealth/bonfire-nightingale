from config import logger

def handle_initial_greeting(db_conn, conversation_id, user_id, ai_json):
    """Send initial greeting message"""
    with db_conn.cursor() as cursor:
        # Update parent name, whatsapp_id if available
        data = ai_json["data"]
        if "parent_name" in data:
            cursor.execute("UPDATE users SET name = %s WHERE id = %s", (data["parent_name"], user_id))
        if "parent_whatsapp_id" in data:
            cursor.execute("UPDATE users SET whatsapp_id = %s WHERE id = %s", (data["parent_whatsapp_id"], user_id))
    db_conn.commit()

def handle_general_purpose(db_conn, conversation_id, user_id, ai_json):
    """Send general purpose message"""
    with db_conn.cursor() as cursor:
        # Update parent name, whatsapp_id if available
        data = ai_json["data"]
        if "parent_name" in data:
            cursor.execute("UPDATE users SET name = %s WHERE id = %s", (data["parent_name"], user_id))
        if "parent_whatsapp_id" in data:
            cursor.execute("UPDATE users SET whatsapp_id = %s WHERE id = %s", (data["parent_whatsapp_id"], user_id))
    db_conn.commit()

def handle_switch_to_coaching(db_conn, conversation_id, user_id, ai_json):
    """Update session mode to coaching, increment session count"""
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE conversations SET mode = 'coaching' WHERE id = %s", (conversation_id,))
        cursor.execute("UPDATE users SET coaching_session_count = coaching_session_count + 1 WHERE id = %s", (conversation_id,))
    db_conn.commit()

def handle_switch_to_concierge(db_conn, conversation_id, user_id, ai_json):
    """Update session mode to concierge, create booking record"""
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE conversations SET mode = 'concierge' WHERE id = %s", (conversation_id,))
    db_conn.commit()
