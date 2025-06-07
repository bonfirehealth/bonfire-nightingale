from typing import Any
from config import logger
from services.email_service import send_booking_confirmation_email

def send_case_to_clinics(case_notes: dict, appointment_id: str):
    """
    Placeholder function to simulate sending case notes to clinics.
    In a real system, this could:
    1. Call an external clinic's API.
    2. Send a formatted email to a distribution list.
    3. Push a message to another SQS queue for a separate processor.
    """
    logger.info(f"Appointment ID: {appointment_id}")
    logger.info(f"Case Notes: {case_notes}")

    success = send_booking_confirmation_email(case_notes, appointment_id)
    if not success:
        return {"status": "error", "message": "Failed to send case to clinics."}

    # Giả sử hành động này luôn thành công trong mô phỏng
    return {"status": "success", "message": "Case sent to clinics for review."}