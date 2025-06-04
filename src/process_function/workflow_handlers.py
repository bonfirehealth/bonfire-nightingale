import logging
from config import app_conf
from wati_service import send_wati_message
from email_service import send_escalation_email
from database import (
    get_active_conversation_state, save_session_outcome,
    log_progress_db, schedule_follow_up_db
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

WTW_KEYWORDS = ["wtw", "handbook", "willis towers watson"]
def check_wtw_request(user_message_text: str) -> bool:
    msg_lower = user_message_text.lower()
    return any(keyword in msg_lower for keyword in WTW_KEYWORDS)

def handle_wtw_response_actions(conn, user_id: str) -> bool:
    handbook_url = app_conf.get("WTW_PARENT_HANDBOOK_URL", "https://default.example.com/wtw_handbook") # Lấy từ config
    message = f"Thank you for reaching out. Happy to help. Here’s the WTW Parent Handbook link: {handbook_url}"
    send_wati_message(user_id, message)
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET wtw_handbook_sent_at = NOW(), is_wtw_employee = TRUE WHERE user_id = %s", (user_id,)) # Giả sử là WTW employee
        conn.commit()
    logger.info(f"WTW handbook link sent to {user_id}")
    return True # Indicated handled

ESCALATION_KEYWORDS = [
    "hopeless", "nothing helps", "i can’t go on", "unsafe", "self-harm",
    "abuse", "suicide", "rape", "kill"
]
def check_escalation_keywords(user_message_text: str) -> bool:
    if any(keyword in user_message_text.lower() for keyword in ESCALATION_KEYWORDS):
        logger.warning(f"ESCALATION DETECTED for user {user_id}. Message: {user_message_text}")
        return True
    return False

def handle_escalation_actions(
    conn,
    user_id: str,
    user_message_text: str,
    conversation_id: int
) -> bool:
    escalation_message = "It sounds like you could use a listening ear. This might be a good moment to speak with our experts. Would you like me to connect you with one of our psychologists?"
    send_wati_message(user_id, escalation_message)
    send_escalation_email(user_id, user_message_text) # Gửi email
    # Cập nhật trạng thái conversation
    if conversation_id:
        with conn.cursor() as cur:
            cur.execute("UPDATE conversations SET is_active = FALSE, escalated_at = NOW() WHERE conversation_id = %s", (conversation_id,))
            conn.commit()
        return True # Indicated handled
    return False

def process_ai_response(
    conn,
    user_id: str,
    conversation_id: int,
    current_conversation_state_json: dict,
    ai_json_response: dict
) -> dict:
    """Process AI response and return next step, new state, and is_active
    
    Args:
        conn (psycopg2.extensions.connection): Database connection
        user_id (str): User ID
        conversation_id (int): Conversation ID
        current_conversation_state_json (dict): Current conversation state
        ai_json_response (dict): AI response
    
    Returns:
        dict: Next step, new state, and is_active
    """
    conversation = get_active_conversation_state(conn, user_id)
    action_type = ai_json_response.get("action_type")
    reply_to_user = ai_json_response.get("reply_message")
    next_sst_step = ai_json_response.get("next_sst_step", conversation.get("current_sst_step")) # Giữ nguyên nếu AI không trả về
    conversation_updates = ai_json_response.get("conversation_update", {})
    
    new_state_for_db = current_conversation_state_json # Bắt đầu với state hiện tại
    if reply_to_user: # Nếu AI có trả lời, thêm vào history
            new_state_for_db["history"].append({"role": "assistant", "content": reply_to_user})
    
    # Merge updates từ AI vào state
    # Điều này quan trọng: AI có thể muốn cập nhật các trường cụ thể trong state_json
    for key, value in conversation_updates.items():
        new_state_for_db[key] = value

    is_conversation_active = True # Mặc định
    outcome_id_for_followup = None

    if action_type == "REPLY_TO_USER" or action_type == "REQUEST_CLARIFICATION":
        if reply_to_user:
            send_wati_message(user_id, reply_to_user)
    elif action_type == "SCHEDULE_FOLLOW_UP":
        if reply_to_user: # Gửi tin nhắn xác nhận trước khi lên lịch
            send_wati_message(user_id, reply_to_user)
        
        summary = ai_json_response.get("session_summary")
        if summary: # Luôn lưu summary khi lên lịch follow-up
            outcome_id_for_followup = save_session_outcome(conn, conversation_id, user_id, summary.get("insight_text"), summary.get("action_step_text"))
        
        follow_up_details = ai_json_response.get("follow_up_details")
        if follow_up_details and outcome_id_for_followup:
            schedule_follow_up_db(conn, user_id, outcome_id_for_followup,
                                    follow_up_details.get("schedule_in_days", 3),
                                    follow_up_details.get("message_template"))
        is_conversation_active = False # Phiên SST kết thúc, chờ follow-up
    elif action_type == "COMPLETE_SESSION_SAVE_SUMMARY":
        if reply_to_user: # Có thể là tin nhắn kết thúc phiên
            send_wati_message(user_id, reply_to_user)
        summary = ai_json_response.get("session_summary")
        if summary:
            save_session_outcome(conn, conversation_id, user_id, summary.get("insight_text"), summary.get("action_step_text"))
        is_conversation_active = False # Phiên SST kết thúc
    elif action_type == "ERROR":
        # error_msg = ai_json_response.get("error_message", "An unexpected error occurred with the AI assistant.")
        send_wati_message(user_id, f"I'm having a little trouble right now. Please try again in a moment.")
        # Không cập nhật next_sst_step hoặc đánh dấu inactive vội, để user thử lại
    elif action_type == "NO_ACTION":
        logger.info(f"AI indicated NO_ACTION for user {user_id}.")
    else:
        logger.warning(f"Unknown action_type from AI: {action_type}")
        send_wati_message(user_id, "I'm not sure how to proceed. Could you try rephrasing?")

    # Log progress nếu AI yêu cầu
    progress_to_log = ai_json_response.get("log_progress")
    if progress_to_log and progress_to_log.get("action_taken"):
        log_progress_db(conn, user_id, progress_to_log.get("action_taken"),
                        progress_to_log.get("reported_outcome"),
                        outcome_id=outcome_id_for_followup) # Gắn với outcome nếu có
    
    return {
        "next_sst_step": next_sst_step,
        "new_state_for_db": new_state_for_db,
        "is_conversation_active": is_conversation_active
    }