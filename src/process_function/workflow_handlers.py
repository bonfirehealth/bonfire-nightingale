import logging
from wati_service import send_wati_message
import database

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
    conversation = database.get_active_conversation_state(conn, user_id)
    action_type = ai_json_response.get("action_type")
    reply_to_user = ai_json_response.get("reply_message")
    next_sst_step = ai_json_response.get("next_sst_step", conversation.get("current_sst_step")) # Giữ nguyên nếu AI không trả về
    conversation_updates = ai_json_response.get("conversation_update", {})
    
    new_state_for_db = current_conversation_state_json # Bắt đầu với state hiện tại
    if reply_to_user: # Nếu AI có trả lời, thêm vào history
        if not new_state_for_db.get("history"):
            new_state_for_db["history"] = []
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
    elif action_type == "PROVIDE_WTW_GUIDEBOOK":
        if reply_to_user:
            send_wati_message(user_id, reply_to_user)
            database.update_user_wtw_status(conn, user_id, is_wtw_employee=True)
    elif action_type == "HANDLE_ESCALATION":
        if reply_to_user:
            send_wati_message(user_id, reply_to_user)
            database.update_user_escalation_status(conn, conversation_id, user_id)
    elif action_type == "SCHEDULE_FOLLOW_UP":
        if reply_to_user: # Gửi tin nhắn xác nhận trước khi lên lịch
            send_wati_message(user_id, reply_to_user)
        
        summary = ai_json_response.get("session_summary")
        if summary: # Luôn lưu summary khi lên lịch follow-up
            outcome_id_for_followup = database.save_session_outcome(conn, conversation_id, user_id, summary.get("insight_text"), summary.get("action_step_text"))
        
        follow_up_details = ai_json_response.get("follow_up_details")
        if follow_up_details and outcome_id_for_followup:
            database.schedule_follow_up_db(conn, user_id, outcome_id_for_followup,
                                    follow_up_details.get("schedule_in_days", 3),
                                    follow_up_details.get("message_template"))
        is_conversation_active = False # Phiên SST kết thúc, chờ follow-up
    elif action_type == "COMPLETE_SESSION_SAVE_SUMMARY":
        if reply_to_user: # Có thể là tin nhắn kết thúc phiên
            send_wati_message(user_id, reply_to_user)
        summary = ai_json_response.get("session_summary")
        if summary:
            database.save_session_outcome(conn, conversation_id, user_id, summary.get("insight_text"), summary.get("action_step_text"))
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
        database.log_progress_db(conn, user_id, progress_to_log.get("action_taken"),
                        progress_to_log.get("reported_outcome"),
                        outcome_id=outcome_id_for_followup) # Gắn với outcome nếu có
    
    return {
        "next_sst_step": next_sst_step,
        "new_state_for_db": new_state_for_db,
        "is_conversation_active": is_conversation_active
    }