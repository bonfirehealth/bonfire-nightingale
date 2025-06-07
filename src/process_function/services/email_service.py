from config import app_conf, logger

def send_clinic_notification(case_notes: dict, conversation_id: str) -> bool:
    logger.info(f"Sending booking confirmation email for appointment {conversation_id}. Case notes: {case_notes}")
    try:
        user_name = case_notes.get("parent_concern", {}).get("name", "Unknown")
        child_age = case_notes.get("child_age", "Unknown")
        sender_email = app_conf.get("GOOGLE_EMAIL_ADDRESS")
        app_password = app_conf.get("GOOGLE_APP_PASSWORD")
        
        # Email addresses từ context hoặc hardcode nếu ít thay đổi
        # Hoặc lưu trong secret khác nếu muốn linh hoạt
        recipient_emails = app_conf.get("BOOKING_CONFIRMATION_EMAIL_RECIPIENTS").split(",") # Lấy từ biến môi trường sẽ tốt hơn
        if not recipient_emails or len(recipient_emails) == 0:
            logger.error("No recipient emails found in configuration.")
            return False
        
        cc_emails = app_conf.get("BOOKING_CONFIRMATION_EMAIL_CC").split(",") # Lấy từ biến môi trường sẽ tốt hơn

        email_subject = app_conf.get("BOOKING_CONFIRMATION_EMAIL_SUBJECT") or "Booking Confirmation"
        final_email_subject = f"{email_subject} - {user_name},{child_age} - {conversation_id}"

        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        # Create message container
        msg = MIMEMultipart("alternative")
        msg["Subject"] = final_email_subject
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipient_emails) # BCC sẽ được xử lý bởi SMTP server khi sendmail
        if cc_emails:
            msg["CC"] = ", ".join(cc_emails)

        # Extract child information from case_notes
        child_name = case_notes.get("child_name", "Unknown")
        assessment_type = case_notes.get("assessment_type", "Unknown")

        # Create HTML content
        html = f"""
        <html>
          <body>
            <p>Hi,</p>
            <p>Please find the appointment details below:</p>
            <table border="1" cellspacing="0" cellpadding="8" style="border-collapse: collapse;">
              <tr>
                <th style="background-color: #f2f2f2; text-align: left;">Field</th>
                <th style="background-color: #f2f2f2; text-align: left;">Value</th>
              </tr>
              <tr>
                <td><strong>Appointment ID</strong></td>
                <td>{conversation_id}</td>
              </tr>
              <tr>
                <td><strong>Child's Name</strong></td>
                <td>{child_name}</td>
              </tr>
              <tr>
                <td><strong>Child's Age</strong></td>
                <td>{child_age}</td>
              </tr>
              <tr>
                <td><strong>Assessment Type</strong></td>
                <td>{assessment_type}</td>
              </tr>
            </table>
            <p>Please review the case.</p>
          </body>
        </html>
        """

        # Attach HTML content
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(sender_email, app_password)
            smtp.sendmail(sender_email, recipient_emails, msg.as_string()) # Gửi tới từng người
        logger.info(f"Booking confirmation email sent to {recipient_emails}")
        return True
    except Exception as e:
        logger.error(f"Error sending booking confirmation email: {e}")
        return False

# --- Google Email Helper ---
def send_escalation_email(user_name: str) -> bool:
    logger.info(f"Sending escalation email to {user_name}")
    try:
        sender_email = app_conf.get("GOOGLE_EMAIL_ADDRESS")
        app_password = app_conf.get("GOOGLE_APP_PASSWORD")
        
        # Email addresses từ context hoặc hardcode nếu ít thay đổi
        # Hoặc lưu trong secret khác nếu muốn linh hoạt
        recipient_emails = app_conf.get("ESCALATION_EMAIL_RECIPIENTS").split(",") # Lấy từ biến môi trường sẽ tốt hơn
        if not recipient_emails or len(recipient_emails) == 0:
            logger.error("No recipient emails found in configuration.")
            return False
        
        cc_emails = app_conf.get("ESCALATION_EMAIL_CC").split(",") # Lấy từ biến môi trường sẽ tốt hơn

        email_subject = app_conf.get("ESCALATION_EMAIL_SUBJECT") or "Nightingale Escalation Alert"

        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(f"An escalation was triggered by a user.\nUser name was: {user_name}\nPlease review the case.")
        msg["Subject"] = email_subject
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipient_emails) # BCC sẽ được xử lý bởi SMTP server khi sendmail
        if cc_emails:
            msg["CC"] = ", ".join(cc_emails)

        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(sender_email, app_password)
            smtp.sendmail(sender_email, recipient_emails, msg.as_string()) # Gửi tới từng người
        logger.info(f"Escalation email sent to {recipient_emails}")
        return True
    except Exception as e:
        logger.error(f"Error sending escalation email: {e}")
        return False
