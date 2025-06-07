from config import logger
import services.email_service as email

def handle_collect_booking_info(db_conn, conversation_id, user_id, ai_json):
    """Update concierge booking with collected information"""
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE concierge_bookings SET status = 'collecting_info' WHERE conversation_id = %s", (conversation_id,))
    db_conn.commit()

def handle_data_collection_complete(db_conn, conversation_id, user_id, ai_json):
    """Mark booking as ready to send to clinics"""
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE concierge_bookings SET status = 'data_complete' WHERE conversation_id = %s", (conversation_id,))
    db_conn.commit()

def handle_send_to_clinics(db_conn, conversation_id, user_id, ai_json):
    """Update booking status, trigger clinic notifications"""
    with db_conn.cursor() as cursor:
        cursor.execute("UPDATE concierge_bookings SET status = 'sent_to_clinics' WHERE conversation_id = %s", (conversation_id,))
    db_conn.commit()

    # Send clinic notification
    case_notes = ai_json["data"]
    email.send_clinic_notification(case_notes, conversation_id)
