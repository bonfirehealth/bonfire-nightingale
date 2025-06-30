import json
import traceback
from typing import Dict, Any

from psycopg2.extensions import cursor as Psycopg2Cursor

from config import logger
from services import (
    database_service as db, openai_service as ai, wati_service as wati,
)
from action_handlers import execute_action

def lambda_handler(event: dict, context: dict) -> dict:
    """
    Main Lambda handler for processing Nightingale AI messages from SQS
    """
    conn = None
    try:
        # 1. Parse incoming request from Wati
        # Wati webhook format might vary. This is a common structure.
        logger.info(f"Received event: {event}")
        record = event.get("Records", [None])[0]
        if not record or "body" not in record:
            logger.error("No valid SQS record found in the event.")
            return {"statusCode": 400, "body": "Invalid event format"}

        # Parse the body of the SQS message
        body = json.loads(record.get("body", "{}"))
        logger.info(f"Received SQS message: {body}")
        
        whatsapp_id = body.get("waId")
        parent_name = body.get("senderName")
        user_message = body.get("text")

        if not whatsapp_id or not user_message:
            logger.error("Missing phone number or message in the request.")
            return {"statusCode": 400, "body": "Invalid request format"}

        # 2. Get DB Connection and create a cursor
        conn = db.get_db_connection()
        with conn.cursor() as cursor:
            
            # 3. Find or create the parent record
            logger.debug(f"Finding or creating parent record for phone number: {whatsapp_id}")
            parent_data = db.get_or_create_parent(cursor, parent_name, whatsapp_id)
            parent_id = parent_data['id']
            
            # 4. Log the incoming user message
            logger.debug(f"Logging user message for parent {parent_id}: {user_message}")
            db.log_message(cursor, parent_id, 'user', user_message)

            # 5. Get conversation history for context
            logger.debug(f"Getting conversation history for parent {parent_id}")
            message_history = db.get_message_history(cursor, parent_id)

            # 6. Construct the prompt for OpenAI
            logger.debug(f"Constructing OpenAI prompt for parent {parent_id}. Message history: {message_history}")
            children = db.get_all_children(cursor, parent_id)
            custom_data = {
                "subscription_plans": ai.get_subscription_plans(cursor),
            }
            prompt = ai.construct_openai_prompt(
                parent_data, children, message_history, user_message, custom_data)

            # 7. Call OpenAI API
            logger.debug(f"Calling OpenAI API for parent {parent_id}")
            ai_response = ai.call_openai_api(prompt)
            
            # 8. Process the action returned by the AI
            logger.debug(f"Processing AI action for parent {parent_id}. AI response: {ai_response}")
            process_ai_action(cursor, parent_id, ai_response)

            # 9. Log the AI's reply
            logger.debug(f"Logging AI reply for parent {parent_id}")
            ai_reply_text = ai_response.get("reply_to_user", "Sorry, I encountered an error.")
            db.log_message(cursor, parent_id, 'ai', ai_reply_text)

            # 10. Commit the database transaction
            logger.debug(f"Committing database transaction for parent {parent_id}")
            conn.commit()
            
            # 11. Send the reply back to the user via Wati
            if not ai_response.get("data", {}).get("suppress_message", False):
                logger.debug(f"Sending AI reply to user {whatsapp_id}")
                wati.send_text_message(whatsapp_id, ai_reply_text)
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
        whatsapp_id = body.get("waId") if 'body' in locals() and isinstance(body, dict) else None
        # if whatsapp_id:
        #     try:
        #         wati.send_text_message(whatsapp_id, "I'm sorry, I seem to be having a technical issue. Please try again in a moment.")
        #     except Exception as notify_err:
        #         logger.error(f"Could not notify user of error: {notify_err}\nTraceback:\n{traceback.format_exc()}")

        return {"statusCode": 500, "body": "Internal Server Error"}

def process_ai_action(cursor: Psycopg2Cursor, parent_id: int, ai_response: Dict[str, Any]) -> None:
    """
    Parses the AI's action and payload, then executes the corresponding database 
    and service operations. This acts as a dispatcher.

    Args:
        cursor (Cursor): The database cursor.
        parent_id (int): The ID of the parent.
        ai_response (Dict[str, Any]): The AI response.
    """
    action = ai_response.get("action", "not_provided")
    execute_action(action, cursor, parent_id, ai_response)
    
    # Update mode
    if "next_mode" in ai_response:
        parent_preferences = {
            "current_mode": ai_response["next_mode"],
            "current_step": ai_response["next_step"]
        }
        db.update_parent_preferences(cursor, parent_id, parent_preferences)
        logger.info(f"Updated mode for parent {parent_id} to {ai_response['next_mode']} and step to {ai_response['next_step']}")
    