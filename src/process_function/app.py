import json
import traceback
import uuid
from typing import Dict, Any
from datetime import datetime, timedelta

import pytz
from psycopg2.extensions import cursor as Psycopg2Cursor

import scheduler
from config import logger
from services import (
    database_service as db, openai_service as ai, wati_service as wati,
    email_service as email
)
from config import SCHEDULE_GROUP_NAME

def lambda_handler(event: dict, context: dict) -> dict:
    """
    Main Lambda handler for processing Nightingale AI messages from SQS
    """
    conn = None
    try:
        # 1. Parse incoming request from Wati
        # Wati webhook format might vary. This is a common structure.
        logger.info(f"Received event: {event}")
        record = event.get("Records")[0]
        body = json.loads(record.get("body", "{}"))
        logger.info(f"Received SQS message: {body}")
        
        user_phone = body.get("waId")
        parent_name = body.get("senderName")
        user_message = body.get("text")

        if not user_phone or not user_message:
            logger.error("Missing phone number or message in the request.")
            return {"statusCode": 400, "body": "Invalid request format"}

        # 2. Get DB Connection and create a cursor
        conn = db.get_db_connection()
        with conn.cursor() as cursor:
            
            # 3. Find or create the parent record
            logger.debug(f"Finding or creating parent record for phone number: {user_phone}")
            parent_data = db.get_or_create_parent(cursor, parent_name, user_phone)
            parent_id = parent_data['id']
            
            # 4. Log the incoming user message
            logger.debug(f"Logging user message for parent {parent_id}: {user_message}")
            db.log_message(cursor, parent_id, 'user', user_message)

            # 5. Get conversation history for context
            logger.debug(f"Getting conversation history for parent {parent_id}")
            message_history = db.get_message_history(cursor, parent_id)

            # 6. Construct the prompt for OpenAI
            logger.debug(f"Constructing OpenAI prompt for parent {parent_id}. Message history: {message_history}")
            prompt = ai.construct_openai_prompt(parent_data, message_history, user_message)

            # 7. Call OpenAI API
            logger.debug(f"Calling OpenAI API for parent {parent_id}")
            ai_response = ai.call_openai_api(prompt)
            
            # 8. Process the action returned by the AI
            logger.debug(f"Processing AI action for parent {parent_id}. AI response: {ai_response}")
            process_ai_actions(cursor, parent_id, ai_response)

            # 9. Log the AI's reply
            logger.debug(f"Logging AI reply for parent {parent_id}")
            ai_reply_text = ai_response.get("reply_to_user", "Sorry, I encountered an error.")
            db.log_message(cursor, parent_id, 'ai', ai_reply_text)

            # 10. Commit the database transaction
            logger.debug(f"Committing database transaction for parent {parent_id}")
            conn.commit()
            
            # 11. Send the reply back to the user via Wati
            if not ai_response.get("data", {}).get("suppress_message", False):
                logger.debug(f"Sending AI reply to user {user_phone}")
                wati.send_wati_message(user_phone, ai_reply_text)
            else:
                logger.debug(f"Suppressing AI reply for parent {parent_id}")

        return {"statusCode": 200, "body": "Message processed successfully"}
    
    except Exception as e:
        # Log the full traceback for debugging
        error_traceback = traceback.format_exc()
        logger.error(f"An unexpected error occurred: {e}\nFull traceback:\n{error_traceback}")
        
        if conn:
            # Rollback any partial changes if an error occurred
            try:
                conn.rollback()
            except Exception as rollback_err:
                logger.error(f"Failed to rollback DB transaction: {rollback_err}")
        
        # Optionally, send a generic error message to the user
        user_phone = body.get("waId") if 'body' in locals() and isinstance(body, dict) else None
        if user_phone:
            try:
                wati.send_wati_message(user_phone, "I'm sorry, I seem to be having a technical issue. Please try again in a moment.")
            except Exception as notify_err:
                logger.error(f"Could not notify user of error: {notify_err}\nTraceback:\n{traceback.format_exc()}")

        return {"statusCode": 500, "body": "Internal Server Error"}

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
        parent_info = db.get_parent_info(cursor, parent_id)
        if parent_info["subscription_status"] == "none":
            logger.info(f"Parent {parent_id} is in none mode. Activating trial mode.")
            db.activate_trial_plan(cursor, parent_id)
        
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

        # Update coaching session
        db.update_coaching_session(cursor, coaching_session)

        logger.info(f"Created coaching session for parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'coaching_session_completed' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_schedule_followup(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    """
    Handles the schedule_followup action.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        data (Dict[str, Any]): The data from the AI response.
    """
    try:
        # 3-day follow-up
        follow_up_sent_at = datetime.now(pytz.utc) + timedelta(days=3) - timedelta(minutes=15)
    
        coaching_session = db.get_or_create_coaching_session(cursor, parent_id, "completed")
        coaching_session["follow_up_scheduled"] = True
        coaching_session["follow_up_sent_at"] = follow_up_sent_at

        # Update coaching session
        db.update_coaching_session(cursor, coaching_session)

        # Schedule nudges
        parent_info = db.get_parent_info(cursor, parent_id)
        scheduler.create_trial_schedules(parent_info["whatsapp_id"], coaching_session["id"])

        scheduler.schedule_single_event(parent_info["whatsapp_id"], coaching_session["id"], "3_day_follow_up", 3)
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'schedule_followup' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_schedule_monthly_summary(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    try:
        # Update parent info
        db.update_monthly_summary_opted_in(cursor, parent_id, True)

        # Schedule monthly summary
        # parent_info = db.get_parent_info(cursor, parent_id)
        # monthly_summary_scheduled_at = datetime.now(pytz.utc) + timedelta(days=30) - timedelta(minutes=15)

        # scheduler.schedule_single_event(parent_info["whatsapp_id"], parent_id, "monthly_summary", 30)

        logger.info(f"Monthly summary scheduled for parent {parent_id}")
    except Exception as e:
        # Log the specific error that occurred during action processing
        error_traceback = traceback.format_exc()
        logger.error(f"Error processing action 'schedule_monthly_summary' for parent {parent_id}: {e}\nTraceback:\n{error_traceback}")
        # Re-raise the error to allow lambda_handler to catch and rollback the transaction
        raise

def handle_coaching_session_succeeded(cursor: Psycopg2Cursor, parent_id: int, data: Dict[str, Any]) -> None:
    try:
        # Update the coaching session = "succeeded"
        coaching_session = db.get_or_create_coaching_session(cursor, parent_id, "completed")
        coaching_session["status"] = "succeeded"
        db.update_coaching_session(cursor, coaching_session)
        logger.info(f"Coaching session succeeded for parent {parent_id}")
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
        parent_info = db.get_parent_info(cursor, parent_id)
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
        import stripe
        reply_to_user = f"Here is the link to subscribe the plan: "

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        session = stripe.checkout.Session.create(
            line_items=[
                {
                    "name": "Parenting Coach Plan",
                    "description": "Monthly subscription for parenting coach",
                    "images": ["https://example.com/logo.png"],
                    "amount": 1000,
                    "currency": "usd",
                    "quantity": 1,
                }
            ],
            mode="subscription",
            client_reference_id=parent_id,
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        parent_info = db.get_parent_info(cursor, parent_id)
        email.send_subscription_link(parent_info["whatsapp_id"], parent_info["full_name"])
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
    "coaching_session_succeeded": handle_coaching_session_succeeded,
    "schedule_followup": handle_schedule_followup,
    "schedule_monthly_summary": handle_schedule_monthly_summary,
    "trigger_escalation": handle_trigger_escalation,
    "provide_subscription_link": handle_provide_subscription_link,
}

def process_ai_actions(cursor: Psycopg2Cursor, parent_id: int, ai_response: Dict[str, Any]) -> None:
    """
    Parses the AI's action and payload, then executes the corresponding database 
    and service operations. This acts as a dispatcher.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        ai_response (Dict[str, Any]): The AI response.
    """
    action = ai_response.get("action")
    data = ai_response.get("data", {})
    handler = ACTION_HANDLERS.get(action, "continue_conversation")
    if handler:
        handler(cursor, parent_id, data)
    else:
        logger.error(f"Unknown or unhandled action type: '{action}' for parent_id: {parent_id}")
    
    # Update mode
    if "next_mode" in ai_response:
        db.update_current_mode(cursor, parent_id, ai_response["next_mode"])
        logger.info(f"Updated mode for parent {parent_id} to {ai_response['next_mode']}")
    
    # Update step
    if "next_step" in ai_response:
        db.update_current_step(cursor, parent_id, ai_response["next_step"])
        logger.info(f"Updated step for parent {parent_id} to {ai_response['next_step']}")