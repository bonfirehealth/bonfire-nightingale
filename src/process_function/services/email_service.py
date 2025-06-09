from config import app_conf, logger

def send_clinic_notification(appointment_info: dict, case_notes: str) -> bool:
    """Send a booking confirmation email to the clinic.

    Args:
        appointment_info (dict): The appointment information.
        case_notes (str): The case notes.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    logger.info(f"Sending booking confirmation email for appointment {appointment_info['id']}. Case notes: {case_notes}")
    try:
        child_name = appointment_info.get("child_name", "Unknown")
        child_age = appointment_info.get("child_age", "Unknown")
        assessment_type = appointment_info.get("assessment_type", "Unknown")
        sender_email = app_conf.get("GOOGLE_EMAIL_ADDRESS")
        app_password = app_conf.get("GOOGLE_APP_PASSWORD")
        
        # Email addresses from context or hardcode if less likely to change
        # Or store in a different secret if you want to be flexible
        recipient_emails = app_conf.get("BOOKING_CONFIRMATION_EMAIL_RECIPIENTS").split(",") # Get from environment variable
        if not recipient_emails or len(recipient_emails) == 0:
            logger.error("No recipient emails found in configuration.")
            return False
        
        cc_emails = app_conf.get("BOOKING_CONFIRMATION_EMAIL_CC").split(",") # Get from environment variable

        email_subject = app_conf.get("BOOKING_CONFIRMATION_EMAIL_SUBJECT") or "Booking Confirmation"
        final_email_subject = f"{email_subject} - {child_name},{child_age} - {appointment_info['id']}"

        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        # Create message container
        msg = MIMEMultipart("alternative")
        msg["Subject"] = final_email_subject
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipient_emails) # BCC will be handled by SMTP server when sendmail
        if cc_emails:
            msg["CC"] = ", ".join(cc_emails)

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
                <td>{appointment_info['id']}</td>
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
            smtp.sendmail(sender_email, recipient_emails, msg.as_string()) # Send to each recipient
        logger.info(f"Booking confirmation email sent to {recipient_emails}")
        return True
    except Exception as e:
        logger.error(f"Error sending booking confirmation email: {e}")
        return False

# --- Google Email Helper ---
def send_escalation_email(user_name: str) -> bool:
    """Send an escalation email to the clinic.

    Args:
        user_name (str): The name of the user.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    logger.info(f"Sending escalation email to {user_name}")
    try:
        sender_email = app_conf.get("GOOGLE_EMAIL_ADDRESS")
        app_password = app_conf.get("GOOGLE_APP_PASSWORD")
        
        # Email addresses from context or hardcode if less likely to change
        # Or store in a different secret if you want to be flexible
        recipient_emails = app_conf.get("ESCALATION_EMAIL_RECIPIENTS").split(",") # Get from environment variable
        if not recipient_emails or len(recipient_emails) == 0:
            logger.error("No recipient emails found in configuration.")
            return False
        
        cc_emails = app_conf.get("ESCALATION_EMAIL_CC").split(",") # Get from environment variable

        email_subject = app_conf.get("ESCALATION_EMAIL_SUBJECT") or "Nightingale Escalation Alert"

        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(f"An escalation was triggered by a user.\nUser name was: {user_name}\nPlease review the case.")
        msg["Subject"] = email_subject
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipient_emails) # BCC will be handled by SMTP server when sendmail
        if cc_emails:
            msg["CC"] = ", ".join(cc_emails)

        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(sender_email, app_password)
            smtp.sendmail(sender_email, recipient_emails, msg.as_string()) # Send to each recipient
        logger.info(f"Escalation email sent to {recipient_emails}")
        return True
    except Exception as e:
        logger.error(f"Error sending escalation email: {e}")
        return False
