import os
from datetime import datetime

import pytz
from psycopg2.extensions import cursor as Psycopg2Cursor

import scheduler
from config import logger
from services import (
    database_service as db,
    wati_service as wati,
    email_service as email,
    stripe_service
)


def handle_continue_conversation(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle basic conversation continuation and trial activation.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data
    """
    data = ai_response.get("data", {})

    # Activate trial if parent is in pre-trial status
    parent_info = db.get_parent_by_id(cursor, parent_id)
    if data.get("trial_activated", False) and parent_info["subscription_status"] == "pre_trial":
        db.activate_trial_plan(cursor, parent_id)
        logger.info(f"Trial activated for parent {parent_id}")
    
    # Create/update child record if provided
    if data.get("child_name"):
        child_record = db.upsert_child(
            cursor, 
            parent_id, 
            data["child_name"], 
            data.get("child_age")
        )
        logger.info(f"Child record updated: {child_record['id']}")
    
    # Set WTW employee flag if parent mentions WTW
    if data.get("is_wtw_employee", False):
        db.update_parent_preferences(cursor, parent_id, {"is_wtw_employee": True})
        logger.info(f"WTW employee flag set for parent {parent_id}")


def handle_send_to_clinics_and_process_payment(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle appointment booking, clinic notification and payment processing.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID  
        ai_response: Response data from AI service containing action-specific data
    """
    data = ai_response.get("data", {})

    # Update parent contact details if provided
    contact_details = data.get("contact_details", {})
    if contact_details:
        db.update_parent_contact_info(cursor, parent_id, contact_details)
    
    # Create appointment record
    appointment_data = {
        "parent_id": parent_id,
        "status": "pending_payment",
        "preferred_time_slot": data.get("preferred_time_slot", ""),
        "assessment_type": data["assessment_type"],
        "case_notes": data.get("case_notes", ""),
        "urgency_level": data.get("urgency_level", "low")
    }
    
    appointment = db.create_appointment(cursor, appointment_data)
    
    # Prepare clinic notification data
    notification_data = {
        **appointment,
        "child_name": data.get("child_name", "Unknown"),
        "child_age": data.get("child_age", "Unknown")
    }
    
    email.send_clinic_notification(notification_data, data.get("case_notes", ""))
    logger.info(f"Appointment created and clinic notified for parent {parent_id}")

    # Send a PayNow QR code to the parent
    parent_info = db.get_parent_by_id(cursor, parent_id)
    wati.send_template_message(parent_info["whatsapp_id"], "paynow_qr", "paynow_qr")

def handle_coaching_session_completed(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle completion of a coaching session.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data
    """
    data = ai_response.get("data", {})

    # Get or create coaching session
    session = db.get_active_coaching_session(cursor, parent_id)
    if not session:
        session = db.create_coaching_session(cursor, parent_id)
    
    # If user's subscription is `pre_trial`, activate trial plan
    parent_info = db.get_parent_by_id(cursor, parent_id)
    if parent_info["subscription_status"] == "pre_trial":
        db.activate_trial_plan(cursor, parent_id)
        logger.info(f"Trial activated for parent {parent_id}")
    
    # Update session with completion data
    session_updates = {
        "status": "completed",
        "session_end_time": datetime.now(pytz.utc),
    }
    
    db.update_coaching_session(cursor, session["id"], session_updates)
    db.increment_session_count(cursor, parent_id)
    
    logger.info(f"Coaching session completed for parent {parent_id}")


def handle_schedule_follow_up(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle follow-up scheduling.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data
    """
    data = ai_response.get("data", {})

    # Get or create coaching session
    session = db.get_active_coaching_session(cursor, parent_id)
    if not session:
        session = db.create_coaching_session(cursor, parent_id)
    
    # Update session with completion data
    session_updates = {
        "status": "completed",
        "session_end_time": datetime.now(pytz.utc),
        "parent_insight": data.get("parent_insight", ""),
        "action_step": data.get("action_step", ""),
        "follow_up_scheduled": data.get("follow_up_scheduled", False),
        "follow_up_outcome": data.get("follow_up_outcome", "pending"),
    }
    
    db.update_coaching_session(cursor, session["id"], session_updates)
    logger.info(f"Updated coaching session {session['id']} for parent {parent_id}")

    parent_info = db.get_parent_by_id(cursor, parent_id)

    # Should we schedule nudges?
    if db.should_schedule_nudges(cursor, parent_id):
        scheduler.create_trial_schedules(parent_info["whatsapp_id"], session["id"])
        logger.info(f"Nudges scheduled for parent {parent_id}")
    else:
        logger.info(f"Parent {parent_id} is not eligible for nudges")

    # Schedule follow-up
    if data.get("follow_up_scheduled", False):
        scheduler.schedule_single_event(
            parent_info["whatsapp_id"], 
            session["id"], 
            "3_day_follow_up", 
            3
        )
        logger.info(f"Coaching session follow-up scheduled for parent {parent_id}")
    else:
        logger.info(f"Follow-up not scheduled for parent {parent_id}")


def handle_schedule_monthly_summary(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle monthly summary subscription.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data (Not used here)
    """
    # Schedule monthly summary
    parent_info = db.get_parent_by_id(cursor, parent_id)
    scheduler.schedule_single_event(
        parent_info["whatsapp_id"], 
        None, 
        "monthly_summary", 
        30
    )
    
    logger.info(f"Monthly summary scheduled for parent {parent_id}")


def handle_update_coaching_session_result(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle follow-up coaching session result update.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data
    """
    data = ai_response.get("data", {})

    # Find the most recent completed session
    session = db.get_latest_coaching_session(cursor, parent_id, "completed")
    if not session:
        logger.warning(f"No completed coaching session found for parent {parent_id}")
        return
    
    # Update follow-up outcome
    outcome = data.get("follow_up_outcome", "failed")
    db.update_coaching_session(cursor, session["id"], {"follow_up_outcome": outcome})
    
    logger.info(f"Coaching session follow-up updated to '{outcome}' for parent {parent_id}")

DEFAULT_DELAY_MINUTES = 2

def handle_offer_voice_call(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle voice call offer.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data
    """
    data = ai_response.get("data", {})

    # Get user preferred language
    user_preferred_language = data.get("user_preferred_language", "english")
    
    parent_info = db.get_parent_by_id(cursor, parent_id)
    if not parent_info:
        logger.error(f"Parent {parent_id} not found")
        return

    # Create a new voice call
    voice_call = db.create_voice_call(cursor, parent_id, user_preferred_language)
    if not voice_call:
        logger.error(f"Failed to create voice call for parent {parent_id}")
        return

    scheduler.schedule_voice_call(
        parent_id=parent_id,
        target_phone=parent_info["whatsapp_id"],
        voice_call_id=voice_call["id"],
        voice_language=user_preferred_language,
        delay_minutes=DEFAULT_DELAY_MINUTES
    )
    logger.info(f"Scheduled a voice call for parent {parent_id}")

def handle_trigger_escalation(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle crisis escalation to human support.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data
    """
    data = ai_response.get("data", {})

    parent_info = db.get_parent_by_id(cursor, parent_id)
    
    # Send escalation email
    email.send_escalation_email(
        parent_info["whatsapp_id"], 
        parent_info["full_name"]
    )
    
    # Log escalation in database
    db.create_escalation_log(cursor, parent_id, data)
    
    logger.info(f"Escalation triggered for parent {parent_id}")

DEFAULT_MESSAGE_FOR_CHECKOUT_ACTION = "Please complete your subscription payment to continue using our services."

def handle_checkout_subscription(cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Handle subscription checkout and payment processing.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data
    """
    data = ai_response.get("data", {})

    # Create Stripe Checkout session
    session = stripe_service.create_checkout_session(parent_id, data.get("subscription_type", "monthly"))

    # Send message to parent with Stripe Checkout URL
    reply_from_ai = ai_response.get("reply_to_user", DEFAULT_MESSAGE_FOR_CHECKOUT_ACTION)
    parent_info = db.get_parent_by_id(cursor, parent_id)
    final_reply_to_user = f"{reply_from_ai}\n{session.url}"
    wati.send_text_message(parent_info["whatsapp_id"], final_reply_to_user)

    # Log the message in the database
    db.log_message(cursor, parent_id, 'ai', final_reply_to_user)
    logger.info(f"Sent subscription checkout message to parent {parent_id}")


# Action handler mapping
ACTION_HANDLERS = {
    "continue_conversation": handle_continue_conversation,
    "send_to_clinics_and_process_payment": handle_send_to_clinics_and_process_payment,
    "complete_coaching_session": handle_coaching_session_completed,
    "update_coaching_session_result": handle_update_coaching_session_result,
    "schedule_follow_up": handle_schedule_follow_up,
    "schedule_monthly_summary": handle_schedule_monthly_summary,
    "offer_voice_call": handle_offer_voice_call,
    "trigger_escalation": handle_trigger_escalation,
    "checkout_subscription": handle_checkout_subscription,
}