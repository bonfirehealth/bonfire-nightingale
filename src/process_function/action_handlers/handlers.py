import traceback
from typing import Dict, Any
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


def handle_continue_conversation(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handle basic conversation continuation and trial activation.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        data: Action data containing optional child info
    """
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


def handle_send_to_clinics(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handle appointment booking and clinic notification.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID  
        data: Appointment and contact data
    """
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

def handle_coaching_session_completed(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handle completion of a coaching session.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        data: Session completion data
    """
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


def handle_schedule_follow_up(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handle follow-up scheduling.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        data: Follow-up scheduling data
    """
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

    # Schedule follow-up
    if data.get("follow_up_scheduled", False):
        scheduler.schedule_single_event(
            parent_info["whatsapp_id"], 
            session["id"], 
            "3_day_follow_up", 
            3
        )
        logger.info(f"Coaching session follow-up scheduled for parent {parent_id}")


def handle_schedule_monthly_summary(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handle monthly summary subscription.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        data: Not used currently
    """
    # Update parent preference
    db.update_parent_preferences(cursor, parent_id, {"monthly_summary_opted_in": True})
    
    # Schedule monthly summary
    parent_info = db.get_parent_by_id(cursor, parent_id)
    scheduler.schedule_single_event(
        parent_info["whatsapp_id"], 
        "", 
        "monthly_summary", 
        30
    )
    
    logger.info(f"Monthly summary scheduled for parent {parent_id}")


def handle_update_coaching_session_result(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handle follow-up coaching session result update.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        data: Follow-up outcome data
    """
    # Find the most recent completed session
    session = db.get_latest_coaching_session(cursor, parent_id, "completed")
    if not session:
        logger.warning(f"No completed coaching session found for parent {parent_id}")
        return
    
    # Update follow-up outcome
    outcome = data.get("follow_up_outcome", "failed")
    db.update_coaching_session(cursor, session["id"], {"follow_up_outcome": outcome})
    
    logger.info(f"Coaching session follow-up updated to '{outcome}' for parent {parent_id}")


def handle_trigger_escalation(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handle crisis escalation to human support.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        data: Escalation context data
    """
    parent_info = db.get_parent_by_id(cursor, parent_id)
    
    # Send escalation email
    email.send_escalation_email(
        parent_info["whatsapp_id"], 
        parent_info["full_name"]
    )
    
    # Log escalation in database
    db.create_escalation_log(cursor, parent_id, data)
    
    logger.info(f"Escalation triggered for parent {parent_id}")


def handle_provide_subscription_link(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handle subscription link generation and delivery.
    
    Args:
        cursor: Database cursor
        parent_id: Parent's ID
        data: May contain suppress_message flag
    """
    parent_info = db.get_parent_by_id(cursor, parent_id)
    
    # Create Stripe checkout session
    session = stripe_service.create_checkout_session(parent_info["whatsapp_id"])
    
    # Send subscription link unless suppressed
    if not data.get("suppress_message", False):
        message = f"Here is the link to subscribe to our plan: {session['url']}"
        wati.send_wati_message(parent_info["whatsapp_id"], message)
    
    logger.info(f"Subscription link provided to parent {parent_id}")


# Action handler mapping
ACTION_HANDLERS = {
    "continue_conversation": handle_continue_conversation,
    "send_to_clinics": handle_send_to_clinics,
    "complete_coaching_session": handle_coaching_session_completed,
    "update_coaching_session_result": handle_update_coaching_session_result,
    "schedule_follow_up": handle_schedule_follow_up,
    "schedule_monthly_summary": handle_schedule_monthly_summary,
    "trigger_escalation": handle_trigger_escalation,
    "provide_subscription_link": handle_provide_subscription_link,
}


def execute_action(action: str, cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Execute the specified action with proper error handling.
    
    Args:
        action: Action type to execute
        cursor: Database cursor
        parent_id: Parent's ID
        data: Action-specific data
        
    Raises:
        Exception: Re-raises any exceptions for transaction rollback
    """
    try:
        handler = ACTION_HANDLERS.get(action)
        if not handler:
            logger.error(f"Unknown action type: '{action}' for parent_id: {parent_id}")
            return
            
        handler(cursor, parent_id, data)
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(
            f"Error executing action '{action}' for parent {parent_id}: {e}\n"
            f"Traceback:\n{error_traceback}"
        )
        raise