from config import logger
import utils

def handle_start_sst_framework(db_conn, conversation_id, user_id, ai_json):
    """Create new coaching session record"""
    with db_conn.cursor() as cursor:
        cursor.execute("INSERT INTO coaching_sessions (conversation_id, user_id, status) VALUES (%s, %s, 'active')", (conversation_id, user_id))
    db_conn.commit()

def handle_coaching_session_complete(db_conn, conversation_id, user_id, ai_json):
    """
    Cập nhật kết quả coaching session, tăng counter, và quan trọng nhất:
    Kích hoạt trial và lên lịch các nudge nếu đây là session đầu tiên.
    """
    try:
        with db_conn.cursor() as cursor:
            # Lấy trạng thái hiện tại của user để ra quyết định
            cursor.execute("SELECT subscription_status, coaching_session_count FROM users WHERE id = %s FOR UPDATE", (user_id,))
            result = cursor.fetchone()
            if not result:
                logger.error(f"User with id {user_id} not found.")
                return

            subscription_status, current_session_count = result

            if subscription_status == "pre_trial":
                logger.info(f"User {user_id} is completing their first session. Activating trial.")
                # Đây là session đầu tiên -> Kích hoạt trial
                cursor.execute("""
                UPDATE users 
                SET subscription_status = 'trialing', 
                    trial_start_date = CURRENT_TIMESTAMP,
                    last_coaching_date = CURRENT_TIMESTAMP,
                    coaching_session_count = 1
                WHERE id = %s
                """, (user_id,))

                # === PHẦN QUAN TRỌNG: GỌI HÀM TẠO SCHEDULES ===
                utils.create_trial_schedules(user_id)

            elif subscription_status in ("trialing", "converted_paid"):
                logger.info(f"User {user_id} is completing another session.")
                # Đây không phải session đầu tiên -> Chỉ cập nhật
                cursor.execute("""
                UPDATE users 
                SET last_coaching_date = CURRENT_TIMESTAMP,
                    coaching_session_count = coaching_session_count + 1
                WHERE id = %s
                """, (user_id,))
            
            # Cập nhật thông tin cho coaching_session
            cursor.execute("""
            UPDATE coaching_sessions 
            SET status = 'completed', 
                completed_at = CURRENT_TIMESTAMP,
                parent_insight = %s,
                micro_step = %s,
                follow_up_scheduled = %s,
                follow_up_date = CASE WHEN %s = true THEN created_at + INTERVAL '3 days' ELSE follow_up_date END
            WHERE conversation_id = %s AND status = 'active'
            """, (
                ai_json["data"].get("parent_insight"),
                ai_json["data"].get("micro_step"),
                ai_json["data"].get("follow_up_scheduled", False),
                ai_json["data"].get("follow_up_scheduled", False),
                conversation_id
            ))

            follow_up_needed = ai_json["data"].get("follow_up_scheduled", False)

            if follow_up_needed:
                logger.info(f"Scheduling a 3-day follow-up for user {user_id}.")
                
                # Chúng ta cần một hàm tương tự như create_trial_schedules
                # nhưng chỉ để tạo một schedule duy nhất.
                # Hàm này có thể được gọi từ nhiều nơi nên hãy tách nó ra.
                try:
                    utils.schedule_single_event(
                        user_id=user_id,
                        conversation_id=conversation_id, # Truyền conversation_id để có ngữ cảnh
                        event_type="3_day_follow_up",
                        days_from_now=3
                    )
                except Exception as e:
                    # Xử lý lỗi nếu việc tạo schedule thất bại
                    # Có thể log lỗi nhưng không cần rollback toàn bộ transaction
                    # vì việc follow-up không quan trọng bằng việc kích hoạt trial.
                    logger.error(f"Failed to schedule 3-day follow-up for user {user_id}. Error: {e}")
        
        # Nếu mọi thứ thành công (bao gồm cả việc tạo schedule), commit transaction
        db_conn.commit()
        logger.info(f"Successfully processed completed session for user {user_id}")

    except Exception as e:
        # Nếu có bất kỳ lỗi nào xảy ra (lỗi DB hoặc lỗi tạo schedule)
        # rollback tất cả các thay đổi trong DB để đảm bảo tính nhất quán.
        logger.error(f"An error occurred in handle_coaching_session_complete for user {user_id}. Rolling back. Error: {e}")
        db_conn.rollback()
