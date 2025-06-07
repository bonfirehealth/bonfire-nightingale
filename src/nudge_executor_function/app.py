from config import logger
from services import database_service as db
from services import wati_service as wati

def lambda_handler(event, context):
    user_id = event.get("userId")
    nudge_type = event.get("nudgeType") # e.g., "day_7", "day_14", "trial_expiry"
    nudge_day = int(nudge_type.split('_')[1]) # Lấy số ngày từ type

    db_conn = db.get_db_connection()
    if nudge_type == "3_day_follow_up":
        logger.info(f"Executing 3-day follow-up for user {user_id}")
        
        message = "How have things been since we last spoke? Did anything shift, even slightly?"
        
        # Gửi tin nhắn qua WhatsApp API
        wati.send_message(user_id, message)
        
        # Ghi nhận lại rằng tin nhắn follow-up đã được gửi (tùy chọn)
        conversation_id = event.get("conversationId")
        if conversation_id:
            with db_conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE coaching_sessions SET follow_up_sent_at = CURRENT_TIMESTAMP WHERE conversation_id = %s",
                    (conversation_id,)
                )
            db_conn.commit()
        
        logger.info(f"Sent 3-day follow-up to user {user_id}")
    elif nudge_type.startswith("nudge_day_") or nudge_type == "trial_expiry":
        # 1. Kiểm tra lần cuối trong DB
        with db_conn.cursor() as cursor:
            can_send = cursor.execute_function('can_send_nudge_to_user', user_id, nudge_day)

        if not can_send:
            logger.info(f"Skipping nudge {nudge_type} for user {user_id}. Condition not met.")
            return

        # 2. Xử lý theo loại nudge
        if nudge_type == "trial_expiry":
            with db_conn.cursor() as cursor:
                cursor.execute("UPDATE users SET subscription_status = 'trial_expired' WHERE id = %s", (user_id,))
            db_conn.commit()
            logger.info(f"Trial expired for user {user_id}.")
            # Có thể gửi một tin nhắn "Trial của bạn đã kết thúc"
        else:
            # Lấy nội dung tin nhắn
            message = get_nudge_message(nudge_type)

            # Gửi tin nhắn qua WhatsApp API
            wati.send_message(user_id, message)

            # Ghi lại vào DB
            with db_conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO trial_nudges (user_id, nudge_day) VALUES (%s, %s)",
                    (user_id, nudge_day)
                )
            db_conn.commit()
            logger.info(f"Sent nudge {nudge_type} to user {user_id}.")

def get_nudge_message(nudge_type):
    messages = {
        "day_7": "Hi, It's been 7 days since you started... Do you want to try another coaching session?",
        "day_14": "Hi, It's been 14 days since you started... Do you want to try another coaching session?",
        "day_28": "Hi, It's been 28 days since you started... Do you want to try another coaching session?"
    }
    return messages.get(nudge_type, "")