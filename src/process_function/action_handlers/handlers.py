import traceback
from typing import Dict, Any
from datetime import datetime, timedelta

import pytz
from psycopg2.extensions import cursor as Psycopg2Cursor

import scheduler
from config import logger
from services import (
    database_service as db, wati_service as wati,
    email_service as email
)

def handle_continue_conversation(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handles the continue_conversation action.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        data (Dict[str, Any]): The data from the AI response.
    """
    try:
        # Check trial status
        parent_info = db.get_parent(cursor, parent_id)
        if parent_info["subscription_status"] == "pre_trial":
            logger.info(f"Parent {parent_id} is in pre_trial mode. Activating trial mode.")
            db.activate_trial_plan(cursor, parent_id)
        
        if data.get("child_name"):
            record = db.get_or_create_child(cursor, parent_id, data["child_name"], data.get("child_age"))
            logger.info(f"Child record created for parent {parent_id}: {record}")
        
        logger.info(f"Continue conversation for parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'continue_conversation' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_send_to_clinics(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handles the send_to_clinics action.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        data (Dict[str, Any]): The data from the AI response.
    """
    try:
        # Parent contact details
        parent_contact_details = data.get("contact_details", {})
        if parent_contact_details:
            db.update_parent_contact_details(cursor, parent_id, parent_contact_details)
            logger.info(f"Updated parent contact details for parent {parent_id}: {parent_contact_details}")
        
        # Create a new appointment object from the data
        insert_appointment = {
            "parent_id": parent_id,
            "status": "pending_payment",
            "preferred_time_slot": data.get("preferred_time_slot", ""),
            "assessment_type": data["assessment_type"],
            "case_notes": data.get("case_notes", ""),
            "urgency_level": data.get("urgency_level", "low")
        }

        appointment = db.create_appointment(cursor, insert_appointment)
        appointment["child_name"] = data.get("child_name", "Unknown")
        appointment["child_age"] = data.get("child_age", "Unknown")
        
        email.send_clinic_notification(appointment, data.get("case_notes", ""))
        logger.info(f"Sent to clinics for parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'send_to_clinics' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_coaching_session_completed(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handles the complete_coaching_session action.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        data (Dict[str, Any]): The data from the AI response.
    """
    try:
        coaching_session = db.get_or_create_coaching_session(cursor, parent_id)
        coaching_session["parent_insight"] = data.get("parent_insight", "")
        coaching_session["action_step"] = data.get("action_step", "")
        coaching_session["status"] = "completed"
        coaching_session["session_end_time"] = datetime.now(pytz.utc)
        coaching_session["follow_up_scheduled"] = data.get("follow_up_scheduled", False)
        coaching_session["follow_up_outcome"] = data.get("follow_up_outcome", "pending")
        coaching_session["monthly_summary_offered"] = data.get("monthly_summary_offered", False)
        coaching_session["monthly_summary_opted_in"] = data.get("monthly_summary_opted_in", False)

        # Update coaching session
        db.update_coaching_session(cursor, coaching_session)

        # Update trial session count
        db.increase_trial_session_count(cursor, parent_id)

        logger.info(f"Created coaching session for parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'coaching_session_completed' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_schedule_monthly_summary(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    try:
        # Update parent info
        db.update_monthly_summary_opted_in(cursor, parent_id, True)

        # Schedule monthly summary
        parent_info = db.get_parent(cursor, parent_id)
        scheduler.schedule_single_event(parent_info["whatsapp_id"], "", "monthly_summary", 30)

        logger.info(f"Monthly summary scheduled for parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'schedule_monthly_summary' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_update_coaching_session_result(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    try:
        # Update the coaching session = "succeeded"
        coaching_session = db.get_or_create_coaching_session(cursor, parent_id, "completed")
        coaching_session["status"] = data.get("follow_up_outcome", "failed")
        db.update_coaching_session(cursor, coaching_session)
        logger.info(f"Coaching session result updated for parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'coaching_session_succeeded' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_trigger_escalation(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handles the trigger_escalation action.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        data (Dict[str, Any]): The data from the AI response.
    """
    try:
        parent_info = db.get_parent(cursor, parent_id)
        email.send_escalation_email(parent_info["whatsapp_id"], parent_info["full_name"])
        db.log_escalation(cursor, parent_id, data)
        logger.info(f"Triggered escalation for parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'trigger_escalation' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_provide_subscription_link(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    try:
        from services.stripe_service import create_checkout_session

        parent_info = db.get_parent(cursor, parent_id)
        session = create_checkout_session(parent_info["whatsapp_id"])
        reply_to_user = f"Here is the link to subscribe the plan: {session['url']}"
        wati.send_wati_message(parent_info["whatsapp_id"], reply_to_user)
        logger.info(f"Sent subscription link to parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'provide_subscription_link' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

ACTION_HANDLERS = {
    "continue_conversation": handle_continue_conversation,
    "send_to_clinics": handle_send_to_clinics,
    "complete_coaching_session": handle_coaching_session_completed,
    "update_coaching_session_result": handle_update_coaching_session_result,
    "schedule_monthly_summary": handle_schedule_monthly_summary,
    "trigger_escalation": handle_trigger_escalation,
    "provide_subscription_link": handle_provide_subscription_link,
}

def execute_action(action: str, cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    try:
        if action in ACTION_HANDLERS:
            ACTION_HANDLERS[action](cursor, parent_id, data)
        else:
            logger.error(f"Unknown action type: '{action}' for parent_id: {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action '{action}' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise
    