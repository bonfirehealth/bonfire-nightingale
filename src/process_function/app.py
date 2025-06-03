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

# --- Database Connection ---
def get_db_connection():
    global db_conn
    if db_conn and db_conn.closed == 0: # Kiểm tra xem kết nối có còn mở không
         try:
            # Kiểm tra xem kết nối có thực sự hoạt động không
            cur = db_conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return db_conn
         except psycopg2.Error:
            logger.info("Database connection was closed or unusable, reconnecting.")
            db_conn = None # Đặt lại để tạo kết nối mới

    if not db_conn or db_conn.closed != 0:
        try:
            db_creds = get_secret(DB_CREDENTIALS_SECRET_ARN)
            db_conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=db_creds['username'],
                password=db_creds['password']
            )
            logger.info("Successfully connected to PostgreSQL database.")
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise
    return db_conn

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
        config = load_app_config()
        wati_api_key = config.get('WATI_API_KEY')
        if not wati_api_key or wati_api_key == "YOUR_WATI_API_KEY_HERE":
            raise ValueError("WATI API key not found or not configured in application secrets.")
        # Logic gọi WATI API (cần thư viện requests hoặc http.client)
        # import requests
        # headers = {"Authorization": f"Bearer {wati_creds['access_token']}"}
        # payload = {"whatsappNumber": recipient_id, "messageText": message_text} # Ví dụ payload
        # response = requests.post(f"{wati_creds['api_endpoint']}/api/v1/sendSessionMessage/{recipient_id}", json=payload, headers=headers) # Đường dẫn API mẫu
        # response.raise_for_status()
        logger.info(f"Sent WATI message to {recipient_id}: {message_text}")
        # Đây là placeholder, bạn cần triển khai thực tế
        print(f"[WATI SIMULATION] To {recipient_id}: {message_text}")
        return True
    except Exception as e:
        logger.error(f"Error sending WATI message: {e}")
        return False
        
# --- Google Email Helper ---
def send_escalation_email(user_message_content):
    try:
        config = load_app_config()
        sender_email = config.get('EMAIL_ADDRESS')
        app_password = config.get('APP_PASSWORD')
        
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

# --- Core Logic ---
def handle_wtw_request(user_id):
    # Gửi link WTW Parent Handbook
    handbook_url = "https://example.com/wtw_parent_handbook" # Thay URL thật
    message = f"Thank you for reaching out. Happy to help. Here’s the parent handbook link: {handbook_url}"
    send_wati_message(user_id, message)
    # Cập nhật trạng thái trong DB (ví dụ: user đã nhận handbook)
    # conn = get_db_connection()
    # with conn.cursor() as cur:
    #     cur.execute("UPDATE users SET wtw_handbook_sent = TRUE WHERE user_id = %s", (user_id,))
    #     conn.commit()
    logger.info(f"WTW handbook link sent to {user_id}")

def check_escalation(user_message_text, user_id):
    escalation_keywords = [
        "hopeless", "nothing helps", "i can’t go on", "unsafe", "self-harm",
        "abuse", "suicide", "rape", "kill"
    ]
    if any(keyword in user_message_text.lower() for keyword in escalation_keywords):
        logger.warning(f"Escalation detected for user {user_id}. Message: {user_message_text}")
        # Gửi tin nhắn tự động cho người dùng
        escalation_message = "It sounds like you could use a listening ear. This might be a good moment to speak with our experts. Would you like me to connect you with one of our psychologists?"
        send_wati_message(user_id, escalation_message)
        # Gửi email
        send_escalation_email(user_message_text)
        # Cập nhật trạng thái trong DB
        # ...
        return True
    return False

def process_sst_sft_flow(user_id, user_message_text, conversation_state):
    # Lấy client OpenAI
    client = get_openai_client()

    # 1. Lấy trạng thái hội thoại hiện tại từ DB (hoặc từ conversation_state)
    current_step = conversation_state.get("current_sst_step", "INIT")
    history = conversation_state.get("history", [])
    history.append({"role": "user", "content": user_message_text})

    # 2. Xây dựng prompt cho OpenAI dựa trên current_step và SFT/SST logic
    # Đây là phần phức tạp nhất, cần logic chi tiết cho từng bước
    # Ví dụ đơn giản:
    system_prompt = """
    You are Nightingale, an AI Parenting Coach using Single Session Therapy (SST) and Solution-Focused Therapy (SFT).
    Guide parents toward one clear insight and one clear next step.
    Your responses should be reflective and empowering, not deep therapy.
    Respond in JSON format: {"reply_message": "Your text here", "next_sst_step": "STEP_X", "action": "NONE|SCHEDULE_FOLLOW_UP|SAVE_SUMMARY", "insight": "...", "next_step_action": "..."}
    """
    
    # Logic để xác định prompt cho từng bước SST
    # STEP 1: Frame the Session
    if current_step == "INIT" or current_step == "START_SST":
        prompt_for_openai = "This is a one-time guided process to help you reflect, gain clarity, and walk away with one meaningful next step. What’s one thing on your mind right now that you wish felt lighter or easier?"
        next_sst_step_val = "SST_STEP_1_AWAIT_RESPONSE"
        ai_response_json = {"reply_message": prompt_for_openai, "next_sst_step": next_sst_step_val, "action": "NONE"}
    
    elif current_step == "SST_STEP_1_AWAIT_RESPONSE":
        # Parent has responded to "What's on your mind?"
        # AI: Acknowledge. Stay curious. No interpretation or advice.
        # AI: "Has there ever been a time — even briefly — when this felt a bit more manageable?"
        user_initial_problem = user_message_text
        # Lưu user_initial_problem vào conversation_state nếu cần
        conversation_state["user_initial_problem"] = user_initial_problem
        
        # OpenAI call để tạo lời acknowledgement + câu hỏi tiếp theo
        messages_for_openai = [
            {"role": "system", "content": system_prompt},
            *history[:-1], # Lịch sử trước đó (nếu có)
            {"role": "user", "content": f"The user shared this: '{user_message_text}'. Acknowledge their response briefly and empathetically. Then ask: 'Has there ever been a time — even briefly — when this felt a bit more manageable?'"}
        ]
        
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo", # Hoặc gpt-4
            messages=messages_for_openai,
            response_format={"type": "json_object"} # Yêu cầu JSON output
        )
        ai_response_json_str = completion.choices[0].message.content
        ai_response_json = json.loads(ai_response_json_str)
        ai_response_json["next_sst_step"] = "SST_STEP_2_AWAIT_RESPONSE" # Cập nhật bước tiếp theo


    # ... Thêm logic cho các bước SST_STEP_2, SST_STEP_3, etc. ...
    # Ví dụ, xử lý câu trả lời cho Step 4 và tạo summary
    elif current_step == "SST_STEP_4_AWAIT_MICRO_STEP_RESPONSE":
        # Parent has offered a micro step
        # AI: "Sounds like you already know more than you realized."
        # AI: "Would you like me to check in with you in 3 days to see how that step went?” [Yes/No]
        conversation_state["next_step_action_proposed"] = user_message_text # Lưu lại bước hành động user đề xuất

        messages_for_openai = [
            {"role": "system", "content": system_prompt},
            *history[:-1],
            {"role": "user", "content": f"The user proposed this micro step: '{user_message_text}'. Respond with: 'Sounds like you already know more than you realized.' Then ask: 'Would you like me to check in with you in 3 days to see how that step went?'"}
        ]
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo", messages=messages_for_openai, response_format={"type": "json_object"}
        )
        ai_response_json_str = completion.choices[0].message.content
        ai_response_json = json.loads(ai_response_json_str)
        ai_response_json["next_sst_step"] = "SST_STEP_5_AWAIT_FOLLOW_UP_CHOICE"

    elif current_step == "SST_STEP_5_AWAIT_FOLLOW_UP_CHOICE":
        # Parent says Yes/No to follow-up
        if "yes" in user_message_text.lower():
            ai_response_json = {"reply_message": "Great! I'll check in with you in 3 days.", "next_sst_step": "SST_COMPLETED_PENDING_FOLLOW_UP", "action": "SCHEDULE_FOLLOW_UP"}
            # Lấy insight và action từ conversation_state để lưu
            ai_response_json["insight"] = conversation_state.get("user_insight_from_step3")
            ai_response_json["next_step_action"] = conversation_state.get("next_step_action_proposed")
        else:
            ai_response_json = {"reply_message": "Okay, sounds good. I'm here if you need anything else.", "next_sst_step": "SST_COMPLETED_NO_FOLLOW_UP", "action": "SAVE_SUMMARY"}
            ai_response_json["insight"] = conversation_state.get("user_insight_from_step3")
            ai_response_json["next_step_action"] = conversation_state.get("next_step_action_proposed")

    else: # Fallback hoặc các bước khác
        logger.warning(f"Unhandled SST step: {current_step}")
        # Gửi một câu hỏi mở lại hoặc fallback
        ai_response_json = {"reply_message": "I'm not sure how to proceed from here. Could you tell me a bit more about what's on your mind?", "next_sst_step": "INIT", "action": "NONE"}


    # 3. Gửi phản hồi AI cho người dùng qua WATI
    send_wati_message(user_id, ai_response_json.get("reply_message", "I'm having a little trouble formulating a response right now."))
    history.append({"role": "assistant", "content": ai_response_json.get("reply_message")})
    
    # 4. Cập nhật trạng thái hội thoại mới vào DB
    new_conversation_state = {
        "current_sst_step": ai_response_json.get("next_sst_step", current_step),
        "history": history[-10:], # Giữ 10 tin nhắn cuối
        "last_insight": ai_response_json.get("insight", conversation_state.get("last_insight")),
        "last_action": ai_response_json.get("next_step_action", conversation_state.get("last_action")),
        # ... các thông tin khác từ conversation_state ...
    }
    # Cập nhật new_conversation_state vào DB cho user_id

    # 5. Thực hiện các actions khác (lên lịch, lưu summary)
    action_to_take = ai_response_json.get("action")
    if action_to_take == "SCHEDULE_FOLLOW_UP":
        # Logic lưu lịch hẹn vào bảng scheduled_follow_ups trong RDS
        # conn = get_db_connection()
        # with conn.cursor() as cur:
        #     # outcome_id sẽ trỏ đến session_outcomes
        #     cur.execute("INSERT INTO scheduled_follow_ups (user_id, outcome_id, scheduled_time, status) VALUES (%s, %s, NOW() + INTERVAL '3 days', 'PENDING')", (user_id, outcome_id_val))
        #     conn.commit()
        logger.info(f"Scheduled follow-up for user {user_id}")
    
    elif action_to_take == "SAVE_SUMMARY":
        # Logic lưu insight và action vào bảng session_outcomes
        # conn = get_db_connection()
        # with conn.cursor() as cur:
        #     cur.execute("INSERT INTO session_outcomes (user_id, insight_text, action_step_text, session_completed_at) VALUES (%s, %s, %s, NOW())",
        #                  (user_id, new_conversation_state['last_insight'], new_conversation_state['last_action']))
        #     conn.commit()
        logger.info(f"Saved session summary for user {user_id}")
        # Gửi summary card nếu có
        summary_card_text = f"Your insight: {new_conversation_state['last_insight']}. Your action: {new_conversation_state['last_action']}. Let’s check in soon." # Hoặc theo logic ở Step 6
        send_wati_message(user_id, summary_card_text)


def lambda_handler(event, context):
    logger.info(f"Received SQS event: {json.dumps(event)}")
    
    # Kết nối DB một lần khi Lambda cold start (hoặc khi cần)
    # get_db_connection() # Có thể gọi ở đầu hoặc khi cần dùng

    for record in event.get('Records', []):
        try:
            wati_payload_str = record.get('body')
            if not wati_payload_str:
                logger.error("SQS record has no body.")
                continue
            
            wati_payload = json.loads(wati_payload_str)
            logger.info(f"Processing WATI payload: {wati_payload}")

            # --- Trích xuất thông tin cần thiết từ WATI payload ---
            # Cấu trúc payload của WATI cần được kiểm tra kỹ. Ví dụ:
            user_id = wati_payload.get('waId') # ID người dùng WhatsApp
            user_message_text = wati_payload.get('text') # Nội dung tin nhắn
            # timestamp = wati_payload.get('timestamp') # Thời gian tin nhắn (epoch ms)
            # is_first_message_of_session = ... # WATI có thể cung cấp thông tin này

            if not user_id or not user_message_text:
                logger.error(f"Missing user_id or text in WATI payload: {wati_payload}")
                continue
            
            # 1. Kiểm tra luồng WTW (nếu là tin nhắn đầu tiên từ user chưa biết)
            # Cần logic để xác định is_first_message hoặc nếu user chưa có trong DB/chưa có conversation_state
            # conn = get_db_connection()
            # with conn.cursor() as cur:
            #     cur.execute("SELECT 1 FROM users WHERE user_id = %s AND is_wtw_employee = TRUE AND wtw_handbook_sent = FALSE", (user_id,))
            #     is_wtw_eligible = cur.fetchone()
            # if is_wtw_eligible and user_message_text.strip().lower() == "hi bonfire team, i'd like the wtw parent handbook please.":
            if user_message_text.strip().lower() == "hi bonfire team, i'd like the wtw parent handbook please.": # Đơn giản hóa, cần logic phức tạp hơn
                handle_wtw_request(user_id)
                continue # Xử lý xong, chuyển sang record tiếp theo

            # 2. Kiểm tra leo thang (Escalation)
            if check_escalation(user_message_text, user_id):
                # Đã xử lý leo thang, không cần tiếp tục luồng SST/SFT
                continue

            # 3. Lấy/Tạo trạng thái hội thoại từ DB
            conversation_state = {} # Lấy từ RDS
            # conn = get_db_connection()
            # with conn.cursor() as cur:
            #     cur.execute("SELECT state_json FROM conversations WHERE user_id = %s AND is_active = TRUE ORDER BY last_interaction_at DESC LIMIT 1", (user_id,))
            #     row = cur.fetchone()
            #     if row and row[0]:
            #         conversation_state = json.loads(row[0])
            #     else: # Tạo conversation mới
            #         cur.execute("INSERT INTO conversations (user_id, current_sst_step, state_json, last_interaction_at) VALUES (%s, 'INIT', %s, NOW()) RETURNING id",
            #                     (user_id, json.dumps({"history": []})))
            #         conversation_id = cur.fetchone()[0]
            #         conn.commit()
            #         conversation_state = {"current_sst_step": "INIT", "history": [], "conversation_id": conversation_id}


            # 4. Xử lý luồng SST/SFT
            process_sst_sft_flow(user_id, user_message_text, conversation_state)

        except Exception as e:
            logger.error(f"Error processing SQS record: {e}", exc_info=True)
            # Không throw lỗi ở đây để Lambda không retry message lỗi liên tục, SQS DLQ sẽ xử lý
            # Nếu muốn retry, có thể throw lỗi có điều kiện.

    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Processed SQS messages'})
    }

# Đóng kết nối DB khi Lambda instance bị shutdown (không đảm bảo được gọi)
# def cleanup():
#     global db_conn
#     if db_conn and db_conn.closed == 0:
#         db_conn.close()
#         logger.info("Database connection closed.")
# import atexit
# atexit.register(cleanup)