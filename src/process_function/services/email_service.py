import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from config import app_conf, logger

# --- Helper function to log retry attempts ---
def log_email_retry_attempt(retry_state):
    """Log the retry attempt details for email sending."""
    logger.warning(
        f"Retrying to send email (attempt {retry_state.attempt_number}) "
        f"due to: {retry_state.outcome.exception()}"
    )

# --- SMTP retry conditions: SMTP connection errors ---
# smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, smtplib.SMTPResponseException
# We can use the parent class smtplib.SMTPException to catch them all
SMTP_RETRYABLE_EXCEPTIONS = (
    smtplib.SMTPException,
    IOError # Catch lower-level network errors
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2), # Wait fixed 2 seconds between attempts
    retry=retry_if_exception_type(SMTP_RETRYABLE_EXCEPTIONS),
    before_sleep=log_email_retry_attempt
)

def send_clinic_notification(appointment_info: dict, case_notes: str) -> bool:
    """Send a booking confirmation email to the clinic.

    Args:
        appointment_info (dict): The appointment information.
        case_notes (str): The case notes.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    logger.info(f"Sending booking confirmation email for appointment {appointment_info['id']}. Case notes: {case_notes}")

    sender_email = app_conf.get("GOOGLE_EMAIL_ADDRESS")
    app_password = app_conf.get("GOOGLE_APP_PASSWORD")
    recipient_emails_str = app_conf.get("BOOKING_CONFIRMATION_EMAIL_RECIPIENTS", "")
    cc_emails_str = app_conf.get("BOOKING_CONFIRMATION_EMAIL_CC", "")

    if not all([sender_email, app_password, recipient_emails_str]):
        logger.error("Email configuration (sender, password, recipients) is incomplete.")
        return False
    
    recipient_emails = [email.strip() for email in recipient_emails_str.split(",") if email.strip()]
    cc_emails = [email.strip() for email in cc_emails_str.split(",") if email.strip()]
    all_recipients = recipient_emails + cc_emails

    child_name = appointment_info.get("child_name", "Unknown")
    child_age = appointment_info.get("child_age", "Unknown")
    assessment_type = appointment_info.get("assessment_type", "Unknown")
    email_subject = app_conf.get("BOOKING_CONFIRMATION_EMAIL_SUBJECT") or "Booking Confirmation"
    final_email_subject = f"{email_subject} - {child_name},{child_age} - {appointment_info['id']}"

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

    try:
        # Use with statement to ensure connection is closed
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp: # Add timeout
            smtp.ehlo()
            smtp.starttls()
            smtp.login(sender_email, app_password)
            smtp.sendmail(sender_email, all_recipients, msg.as_string())
        
        logger.info(f"Booking confirmation email sent successfully to {all_recipients}")
        return True
    except smtplib.SMTPAuthenticationError as auth_err:
        # Authentication error -> should not retry, issue is with configuration
        logger.error(f"SMTP Authentication failed. Check email/password. Error: {auth_err}")
        return False # Return False to prevent Lambda failure
    except Exception as e:
        # Other exceptions (e.g., SMTPException) will be thrown to tenacity to catch and retry
        logger.error(f"An error occurred while sending email: {e}")
        raise

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(SMTP_RETRYABLE_EXCEPTIONS),
    before_sleep=log_email_retry_attempt
)
def send_escalation_email(whatsapp_id: str, user_name: str) -> bool:
    """Send an escalation email to the clinic.

    Args:
        whatsapp_id (str): The whatsapp id of the user.
        user_name (str): The name of the user.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    logger.info(f"Attempting to send escalation email for user {user_name}")

    sender_email = app_conf.get("GOOGLE_EMAIL_ADDRESS")
    app_password = app_conf.get("GOOGLE_APP_PASSWORD")
    recipient_emails_str = app_conf.get("ESCALATION_EMAIL_RECIPIENTS", "")
    
    if not all([sender_email, app_password, recipient_emails_str]):
        logger.error("Escalation email configuration is incomplete.")
        return False
        
    recipient_emails = [email.strip() for email in recipient_emails_str.split(",") if email.strip()]
    cc_emails_str = app_conf.get("ESCALATION_EMAIL_CC", "")
    cc_emails = [email.strip() for email in cc_emails_str.split(",") if email.strip()]

    email_subject = app_conf.get("ESCALATION_EMAIL_SUBJECT") or "Nightingale Escalation Alert"

    msg = MIMEText(f"An escalation was triggered by a user.\nUser name was: {user_name}. WhatsApp ID: {whatsapp_id}\nPlease review the case.")
    msg["Subject"] = email_subject
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipient_emails) # BCC will be handled by SMTP server when sendmail
    if cc_emails:
        msg["CC"] = ", ".join(cc_emails)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(sender_email, app_password)
            smtp.sendmail(sender_email, recipient_emails, msg.as_string()) # Send to each recipient
        
        logger.info(f"Escalation email sent successfully to {recipient_emails}")
        return True
    except smtplib.SMTPAuthenticationError as auth_err:
        logger.error(f"SMTP Authentication failed. Check email/password. Error: {auth_err}")
        return False
    except Exception as e:
        logger.error(f"An error occurred while sending escalation email: {e}")
        raise