import logging
from config import app_conf

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Google Email Helper ---
def send_escalation_email(user_name: str) -> bool:
    logger.info(f"Sending escalation email to {user_name}")
    try:
        sender_email = app_conf.get('GOOGLE_EMAIL_ADDRESS')
        app_password = app_conf.get('GOOGLE_APP_PASSWORD')
        
        # Email addresses từ context hoặc hardcode nếu ít thay đổi
        # Hoặc lưu trong secret khác nếu muốn linh hoạt
        recipient_emails = app_conf.get('ESCALATION_EMAIL_RECIPIENTS').split(",") # Lấy từ biến môi trường sẽ tốt hơn
        if not recipient_emails or len(recipient_emails) == 0:
            logger.error("No recipient emails found in configuration.")
            return False
        
        cc_emails = app_conf.get('ESCALATION_EMAIL_CC').split(",") # Lấy từ biến môi trường sẽ tốt hơn

        email_subject = app_conf.get('ESCALATION_EMAIL_SUBJECT') or "Nightingale Escalation Alert"

        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(f"An escalation was triggered by a user.\nUser name was: {user_name}\nPlease review the case.")
        msg['Subject'] = email_subject
        msg['From'] = sender_email
        msg['To'] = ", ".join(recipient_emails) # BCC sẽ được xử lý bởi SMTP server khi sendmail
        if cc_emails:
            msg['CC'] = ", ".join(cc_emails)

        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(sender_email, app_password)
            smtp.sendmail(sender_email, recipient_emails, msg.as_string()) # Gửi tới từng người
        logger.info(f"Escalation email sent to {recipient_emails}")
        return True
    except Exception as e:
        logger.error(f"Error sending escalation email: {e}")
        return False
