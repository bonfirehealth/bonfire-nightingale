import psycopg2

from config import logger
from services import email_service as email

def handle_update_child_details(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Update child details

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    child_details = ai_json["data"]
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE children SET name = %s, age = %s WHERE parent_id = %s", (child_details["child_name"], child_details["child_age"], user_id))
    db_conn.commit()

def handle_update_assessment_type(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Update assessment type

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE concierge_bookings SET assessment_type = %s WHERE conversation_id = %s", (ai_json["data"]["assessment_type"], conversation_id))
    db_conn.commit()

def handle_update_preferred_time(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Update preferred time

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE concierge_bookings SET preferred_time = %s WHERE conversation_id = %s", (ai_json["data"]["preferred_time"], conversation_id))
    db_conn.commit()

def handle_update_contact_details(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Update contact details

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    contact_details = ai_json["data"]["contact_details"]
    with db_conn.cursor() as cursor:
        cursor.execute("""
            UPDATE users 
            SET name = %s, whatsapp_id = %s, email = %s, postal_code = %s 
            WHERE id = %s
        """, (
            contact_details["name"], 
            contact_details["phone"], 
            contact_details["email"], 
            contact_details["postal_code"], 
            user_id
        ))
    db_conn.commit()

def handle_data_collection_complete(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Mark booking as ready to send to clinics

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    data = ai_json["data"]
    contact_details = data["contact_details"]
    with db_conn.cursor() as cursor:
        # Update parent details
        cursor.execute("UPDATE users SET name = %s, whatsapp_id = %s, email = %s, postal_code = %s WHERE id = %s", (
            contact_details["name"], 
            contact_details["phone"], 
            contact_details["email"], 
            contact_details["postal_code"], 
            user_id
        ))
        # Update child details
        cursor.execute("UPDATE children SET name = %s, age = %s WHERE parent_id = %s", (data["child_name"], data["child_age"], user_id))
        # Update booking status
        cursor.execute("""
            UPDATE concierge_bookings 
            SET status = 'data_complete', 
                assessment_type = %s, 
                preferred_time = %s
            WHERE conversation_id = %s
        """, (
            data["assessment_type"], 
            data["preferred_time"], 
            conversation_id
        ))

        if data.get("specific_datetime", ""):
            cursor.execute("UPDATE concierge_bookings SET specific_datetime = %s WHERE conversation_id = %s", (data["specific_datetime"], conversation_id))
    db_conn.commit()

def handle_send_to_clinics(db_conn: psycopg2.connect, conversation_id: str, user_id: str, ai_json: dict) -> None:
    """Update booking status, trigger clinic notifications

    Args:
        db_conn (psycopg2.connect): The database connection.
        conversation_id (str): The conversation ID.
        user_id (str): The user ID.
        ai_json (dict): The AI JSON.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE concierge_bookings SET status = 'sent_to_clinics' WHERE conversation_id = %s", (conversation_id,))
    db_conn.commit()

    # Send clinic notification
    case_notes = ai_json["data"]["case_notes"]
    email.send_clinic_notification(case_notes, conversation_id)
