import json
import os
import boto3
import logging
import psycopg2 # Hoặc pg8000 nếu dùng RDS Data API
from openai import OpenAI # Hoặc from openai import OpenAI

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Environment Variables & Secrets ---
DB_HOST = os.environ.get('DB_HOST')
DB_PORT = os.environ.get('DB_PORT')
DB_NAME = os.environ.get('DB_NAME')
DB_CREDENTIALS_SECRET_ARN = os.environ.get('DB_CREDENTIALS_SECRET_ARN')
APPLICATION_SECRETS_ARN = os.environ.get('APPLICATION_SECRETS_ARN') # ARN của Secret JSON

secrets_client = boto3.client('secretsmanager')
db_conn = None
app_config = None

def get_secret(secret_arn):
    try:
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        logger.info(f"Response: {response} {type(response)}")
        if 'SecretString' in response:
            return json.loads(response['SecretString'])
        else:
            # Xử lý binary secret nếu cần
            return json.loads(response['SecretBinary'].decode('utf-8'))
    except Exception as e:
        logger.error(f"Error getting secret {secret_arn}: {e}")
        raise

def load_app_config():
    global app_config
    if app_config is None:
        try:
            logger.info(f"Loading application configuration from Secrets Manager: {APPLICATION_SECRETS_ARN}")
            app_config = get_secret(APPLICATION_SECRETS_ARN)
            logger.info("Application configuration loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load application configuration: {e}")
            # Quyết định hành vi khi không load được config (ví dụ: raise error để Lambda fail)
            raise RuntimeError(f"Could not load application configuration from {APPLICATION_SECRETS_ARN}") from e
    return app_config

# --- OpenAI Client ---
openai_client = None
def get_openai_client():
    global openai_client
    if openai_client is None:
        config = load_app_config()
        openai_api_key = config.get('OPENAI_API_KEY')
        if not openai_api_key:
            raise ValueError("OpenAI API key not found or not configured in application secrets.")
        openai_client = OpenAI(api_key=openai_api_key)
    return openai_client

# --- WATI API Helper ---
def send_wati_message(recipient_id, message_text):
    try:
        logger.info(f"Sending WATI message: `{message_text}` to {recipient_id}")
        config = load_app_config()
        wati_access_token = config.get('WATI_ACCESS_TOKEN')
        if not wati_access_token:
            raise ValueError("WATI Access Token not found or not configured in application secrets.")
        
        wati_api_endpoint = config.get('WATI_API_ENDPOINT')
        if not wati_api_endpoint:
            raise ValueError("WATI API Endpoint not found or not configured in application secrets.")
        
        logger.info(f"WATI API Endpoint: {wati_api_endpoint}")
        import requests
        headers = {
            "Content-type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {wati_access_token}"
        }
        payload = {"messageText": message_text}
        url = f"{wati_api_endpoint}/api/v1/sendSessionMessage/{recipient_id}"
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"Sent WATI message to {recipient_id}: {message_text}")
        return True
    except Exception as e:
        logger.error(f"Error sending WATI message: {e}")
        return False

# --- Google Email Helper ---
def send_escalation_email(user_message_content):
    try:
        config = load_app_config()
        sender_email = config.get('GOOGLE_EMAIL_ADDRESS')
        app_password = config.get('GOOGLE_APP_PASSWORD')
        
        # Email addresses từ context hoặc hardcode nếu ít thay đổi
        # Hoặc lưu trong secret khác nếu muốn linh hoạt
        recipient_emails = ["Dr.Reale@gmail.com", "jane@pebblepsychology.com"] # Lấy từ biến môi trường sẽ tốt hơn

        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(f"An escalation was triggered by a user.\nUser message was: {user_message_content}\nPlease review the case.")
        msg['Subject'] = 'Nightingale Escalation Alert - Nightingale'
        msg['From'] = sender_email
        msg['To'] = ", ".join(recipient_emails) # BCC sẽ được xử lý bởi SMTP server khi sendmail

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
           smtp_server.login(sender_email, app_password)
           smtp_server.sendmail(sender_email, recipient_emails, msg.as_string()) # Gửi tới từng người
        logger.info(f"Escalation email sent to {recipient_emails}")
        return True
    except Exception as e:
        logger.error(f"Error sending escalation email: {e}")
        return False

# --- Database Connection ---
def get_or_create_user(conn, user_id, user_name=None):
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
            SELECT conversation_id, current_sst_step, conversation_state_json
            FROM conversations
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY last_interaction_at DESC
            LIMIT 1
        """, (user_id,))
        convo = cur.fetchone()
        if convo:
            logger.info(f"Active conversation found for {user_id}: ID {convo[0]}")
            return {"conversation_id": convo[0], "current_sst_step": convo[1], "state_json": convo[2] or {}}
    logger.info(f"No active conversation found for {user_id}.")
    return None

def create_new_conversation(conn, user_id, initial_step="INIT", initial_state_json=None):
    if initial_state_json is None:
        initial_state_json = {"history": []} # Bắt đầu với history rỗng
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO conversations (user_id, current_sst_step, conversation_state_json)
            VALUES (%s, %s, %s)
            RETURNING conversation_id, current_sst_step, conversation_state_json
        """, (user_id, initial_step, json.dumps(initial_state_json)))
        new_convo = cur.fetchone()
        conn.commit()
        logger.info(f"New conversation created for {user_id}: ID {new_convo[0]}")
        return {"conversation_id": new_convo[0], "current_sst_step": new_convo[1], "state_json": new_convo[2]}

def update_conversation_state(conn, conversation_id, next_sst_step, new_state_json, is_active=True):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE conversations
            SET current_sst_step = %s, conversation_state_json = %s, last_interaction_at = NOW(), is_active = %s
            WHERE conversation_id = %s
        """, (next_sst_step, json.dumps(new_state_json), is_active, conversation_id))
        conn.commit()
        logger.info(f"Conversation {conversation_id} updated. Next step: {next_sst_step}, Active: {is_active}")

def save_session_outcome(conn, conversation_id, user_id, insight, action_step):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO session_outcomes (conversation_id, user_id, insight_text, action_step_text)
            VALUES (%s, %s, %s, %s) RETURNING outcome_id
        """, (conversation_id, user_id, insight, action_step))
        outcome_id = cur.fetchone()[0]
        conn.commit()
        logger.info(f"Session outcome saved for conversation {conversation_id}, outcome_id: {outcome_id}")
        return outcome_id

def schedule_follow_up_db(conn, user_id, outcome_id, schedule_in_days, message_template):
    scheduled_time = datetime.now(timezone.utc) + timedelta(days=schedule_in_days)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scheduled_follow_ups (user_id, outcome_id, scheduled_time, follow_up_message_template, status)
            VALUES (%s, %s, %s, %s, 'PENDING')
        """, (user_id, outcome_id, scheduled_time, message_template))
        conn.commit()
        logger.info(f"Follow-up scheduled for user {user_id} at {scheduled_time}")

def log_progress_db(conn, user_id, action_taken, reported_outcome=None, outcome_id=None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO progress_tracking (user_id, outcome_id, action_taken, reported_outcome)
            VALUES (%s, %s, %s, %s)
        """,(user_id, outcome_id, action_taken, reported_outcome))
        conn.commit()
        logger.info(f"Progress logged for user {user_id}: {action_taken}")

# --- Workflow Handlers ---
WTW_KEYWORDS = ["wtw", "handbook", "willis towers watson"]
def check_wtw_request(user_message_text):
    msg_lower = user_message_text.lower()
    return any(keyword in msg_lower for keyword in WTW_KEYWORDS)

def handle_wtw_request(conn, user_id):
    config = load_app_config()
    handbook_url = config.get("WTW_PARENT_HANDBOOK_URL", "https://default.example.com/wtw_handbook") # Lấy từ config
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
def check_escalation(user_message_text, user_id, conversation_id, conn):
    if any(keyword in user_message_text.lower() for keyword in ESCALATION_KEYWORDS):
        logger.warning(f"ESCALATION DETECTED for user {user_id}. Message: {user_message_text}")
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

def call_openai_assistant(user_id, user_message_text, conversation_state):
    client = get_openai_client()
    # Đây là nơi bạn sẽ xây dựng prompt dựa trên conversation_state và user_message_text
    # Prompt của bạn nên hướng dẫn AI trả về JSON theo cấu trúc đã đề xuất.
    # Ví dụ:
    # system_prompt = "You are Nightingale... Your response MUST be a JSON object with fields: action_type, reply_message, next_sst_step, conversation_update..."
    system_prompt = ""
    with open("system_prompt.txt", "r") as f:
        system_prompt = f.read()
    messages_to_openai = [
        {"role": "system", "content": system_prompt},
        *(conversation_state.get("state_json", {}).get("history", [])), # Lịch sử hội thoại
        {"role": "user", "content": user_message_text}
    ]
    logger.info(f"Sending to OpenAI for user {user_id}: {json.dumps(messages_to_openai)}")

    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo", # Hoặc model bạn chọn
            messages=messages_to_openai,
            response_format={"type": "json_object"} # Yêu cầu JSON output
        )
        ai_response_str = completion.choices[0].message.content
        logger.info(f"Raw response from OpenAI: {ai_response_str}")
        ai_json_response = json.loads(ai_response_str)
        return ai_json_response
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response from OpenAI: {e}. Response: {ai_response_str}", exc_info=True)
        return {"action_type": "ERROR", "error_message": "AI response format error."}
    except Exception as e:
        logger.error(f"Error calling OpenAI: {e}", exc_info=True)
        return {"action_type": "ERROR", "error_message": "Could not reach AI assistant."}

# --- Main Lambda Handler ---
def lambda_handler(event, context):
    logger.info(f"Received SQS event in {ENVIRONMENT_NAME}: {json.dumps(event, indent=2)}")
    load_app_config() # Load config một lần nếu chưa có
    conn = None # Khởi tạo conn

    for record in event.get('Records', []):
        try:
            wati_payload_str = record.get('body')
            if not wati_payload_str:
                logger.error("SQS record has no body.")
                continue

            wati_payload = json.loads(wati_payload_str)
            logger.info(f"Processing WATI payload: {json.dumps(wati_payload, indent=2)}")

            user_id = wati_payload.get('waId') # ID người dùng WhatsApp
            user_message_text = wati_payload.get('text', '').strip() # Nội dung tin nhắn
            user_name = wati_payload.get('senderName') # Tên người gửi (nếu có)

            if not user_id or not user_message_text:
                logger.error(f"Missing user_id or text in WATI payload: {wati_payload}")
                continue

            conn = get_db_connection() # Mở kết nối DB cho mỗi record (hoặc tái sử dụng)
            db_user_profile = get_or_create_user(conn, user_id, user_name)

            # 1. Check WTW employee (keyword-based)
            if check_wtw_request(user_message_text):
                if not db_user_profile.get("wtw_handbook_sent_at"): # Chỉ gửi nếu chưa gửi
                    handle_wtw_request(conn, user_id)
                else:
                    logger.info(f"WTW handbook already sent to {user_id}. Skipping WTW handler.")
                    # Có thể gửi một tin nhắn khác hoặc để OpenAI xử lý như bình thường
                    send_wati_message(user_id, "I see you've already received the WTW handbook. How else can I help you today?")
                continue # Xử lý xong, bỏ qua các bước sau cho message này

            # 2. Get or Create Conversation State
            conversation = get_active_conversation_state(conn, user_id)
            if not conversation:
                conversation = create_new_conversation(conn, user_id)
            
            current_conversation_id = conversation.get("conversation_id")

            # 3. Check Escalation
            if check_escalation(user_message_text, user_id, current_conversation_id, conn):
                # Escalation đã xử lý, không cần gọi OpenAI
                continue

            # 4. Call OpenAI Assistant
            # Đính kèm conversation_state (bao gồm history) và message mới
            # current_conversation_state_json là dict đã parse
            current_conversation_state_json = conversation.get("state_json", {})
            if not isinstance(current_conversation_state_json.get("history"), list):
                current_conversation_state_json["history"] = []
            current_conversation_state_json["history"].append({"role": "user", "content": user_message_text})
            
            # Chuẩn bị payload cho OpenAI (chỉ gửi phần state_json và current_sst_step)
            payload_for_openai = {
                "current_sst_step": conversation.get("current_sst_step"),
                "state_json": current_conversation_state_json
            }

            ai_response = call_openai_assistant(user_id, user_message_text, payload_for_openai)
            logger.info(f"AI Response for user {user_id}: {json.dumps(ai_response, indent=2)}")

            # 5. Process AI Response and take actions
            action_type = ai_response.get("action_type")
            reply_to_user = ai_response.get("reply_message")
            next_sst_step = ai_response.get("next_sst_step", conversation.get("current_sst_step")) # Giữ nguyên nếu AI không trả về
            conversation_updates = ai_response.get("conversation_update", {})
            
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
                
                summary = ai_response.get("session_summary")
                if summary: # Luôn lưu summary khi lên lịch follow-up
                    outcome_id_for_followup = save_session_outcome(conn, current_conversation_id, user_id, summary.get("insight_text"), summary.get("action_step_text"))
                
                follow_up_details = ai_response.get("follow_up_details")
                if follow_up_details and outcome_id_for_followup:
                    schedule_follow_up_db(conn, user_id, outcome_id_for_followup,
                                          follow_up_details.get("schedule_in_days", 3),
                                          follow_up_details.get("message_template"))
                is_conversation_active = False # Phiên SST kết thúc, chờ follow-up
            elif action_type == "COMPLETE_SESSION_SAVE_SUMMARY":
                if reply_to_user: # Có thể là tin nhắn kết thúc phiên
                    send_wati_message(user_id, reply_to_user)
                summary = ai_response.get("session_summary")
                if summary:
                    save_session_outcome(conn, current_conversation_id, user_id, summary.get("insight_text"), summary.get("action_step_text"))
                is_conversation_active = False # Phiên SST kết thúc
            elif action_type == "ERROR":
                error_msg = ai_response.get("error_message", "An unexpected error occurred with the AI assistant.")
                send_wati_message(user_id, f"I'm having a little trouble right now. Please try again in a moment. ({error_msg})")
                # Không cập nhật next_sst_step hoặc đánh dấu inactive vội, để user thử lại
            elif action_type == "NO_ACTION":
                logger.info(f"AI indicated NO_ACTION for user {user_id}.")
            else:
                logger.warning(f"Unknown action_type from AI: {action_type}")
                send_wati_message(user_id, "I'm not sure how to proceed. Could you try rephrasing?")

            # Log progress nếu AI yêu cầu
            progress_to_log = ai_response.get("log_progress")
            if progress_to_log and progress_to_log.get("action_taken"):
                log_progress_db(conn, user_id, progress_to_log.get("action_taken"),
                                progress_to_log.get("reported_outcome"),
                                outcome_id=outcome_id_for_followup) # Gắn với outcome nếu có


            # Cập nhật conversation state vào DB (chỉ nếu không phải escalation đã handled)
            # Giới hạn kích thước history để tránh state_json quá lớn
            if "history" in new_state_for_db and isinstance(new_state_for_db["history"], list):
                new_state_for_db["history"] = new_state_for_db["history"][-20:] # Giữ 20 cặp hội thoại cuối

            update_conversation_state(conn, current_conversation_id, next_sst_step, new_state_for_db, is_active=is_conversation_active)

        except psycopg2.Error as db_err: # Lỗi DB cụ thể
            logger.error(f"Database error processing SQS record: {db_err}", exc_info=True)
            if conn: conn.rollback() # Quan trọng: rollback nếu có lỗi DB
            # Quyết định có re-queue message không (bằng cách raise error lại)
            # Hoặc nếu lỗi là tạm thời, có thể không raise để SQS tự retry sau visibility timeout
            # Nếu lỗi nghiêm trọng, message sẽ vào DLQ sau vài lần retry
            # raise db_err # Để SQS retry
        except Exception as e:
            logger.error(f"Generic error processing SQS record: {e}", exc_info=True)
            if conn and not conn.closed: conn.rollback()
            # raise e # Để SQS retry
        finally:
            # Không đóng kết nối ở đây nếu muốn tái sử dụng cho các record tiếp theo trong cùng 1 invocation
            # Lambda sẽ tự quản lý việc đóng kết nối khi container bị reused hoặc shutdown.
            # Nếu bạn muốn đóng sau mỗi record:
            # if conn and not conn.closed:
            #     conn.close()
            #     logger.info("DB connection closed for record.")
            #     conn = None
            pass
            
    # Đóng kết nối nếu nó vẫn mở sau khi xử lý hết các record (cho cold start/shutdown)
    global db_conn # Cần khai báo global để có thể gán lại db_conn = None
    if db_conn and not db_conn.closed:
        db_conn.close()
        logger.info("DB connection closed at the end of Lambda invocation.")
        db_conn = None

    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Processed SQS messages successfully'})
    }