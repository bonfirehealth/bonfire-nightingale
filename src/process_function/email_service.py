import logging
from config import app_conf

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Google Email Helper ---
def send_escalation_email(user_message_content):
    try:
        sender_email = app_conf.get('GOOGLE_EMAIL_ADDRESS')
        app_password = app_conf.get('GOOGLE_APP_PASSWORD')
        
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
