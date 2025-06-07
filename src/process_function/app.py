import json
import traceback

from services import database_service as db
from services import openai_service as ai
from services import wati_service as wati
from services import email_service as email
from datetime import datetime, timedelta
from handlers import common_handler as cm_handler, concierge_handler as cc_handler, parenting_coach_handler as pc_handler
from config import logger

def lambda_handler(event, context):
    """
    Main Lambda handler for processing Nightingale AI messages from SQS
    """
    try:
        # ========================================
        # 1. PARSE SQS MESSAGE
        # ========================================
        try:
            # Extract message from SQS event
            sqs_record = event["Records"][0]  # Assuming single message processing
            message_body = json.loads(sqs_record["body"])
            logger.info(f"Received SQS message: {message_body}")
            
            whatsapp_id = message_body["waId"]
            user_name = message_body.get("senderName")
            user_message = message_body["text"]
            
        except Exception as e:
            logger.error(f"Failed to parse SQS message: {str(e)}\n{traceback.format_exc()}")
            return error_response(f"Failed to parse SQS message: {str(e)}")

        # ========================================
        # 2. DATABASE CONNECTION & USER LOOKUP
        # ========================================
        db_conn = None
        try:
            db_conn = db.get_db_connection()
            # Get or create user conversation
            user = db.get_or_create_user(db_conn, whatsapp_id)
            logger.debug(f"User found: {user}")
            conversation = db.get_or_create_conversation(db_conn, user["id"])
            logger.debug(f"Conversation found: {conversation}")
            conversation_id = conversation["id"]
            
        except Exception as e:
            logger.error(f"Database error: {str(e)}\n{traceback.format_exc()}")
            return error_response(f"Database error: {str(e)}")

        try:
            # ========================================
            # 3. BUILD AI CONTEXT
            # ========================================
            user["name"] = user_name
            ai_context = ai.build_ai_context(
                conversation_id=conversation_id,
                user=user,
                conversation_history=db.get_recent_messages(db_conn, conversation_id, limit=10),
                trial_status=db.check_trial_status(db_conn, user["id"]),
                user_message=user_message
            )
            try:
                logger.info(f"Calling AI with context: {ai_context}")
                ai_json = ai.get_ai_response(
                    input_context=ai_context
                )
                
            except Exception as e:
                logger.error(f"AI error: {str(e)}\n{traceback.format_exc()}")
                # Fallback response if AI fails
                ai_json = create_fallback_response()

            # ========================================
            # 5. SAVE MESSAGE TO DATABASE
            # ========================================
            logger.debug(f"Saving user message to database: {user_message}")
            db.save_message(db_conn, conversation_id, "user", user_message, "text")
            logger.debug(f"Saving AI response to database: {ai_json['message']}")
            db.save_message(db_conn, conversation_id, "nightingale", ai_json["message"], "text")

            # ========================================
            # 6-9. PROCESS ACTIONS & WORKFLOWS
            # ========================================
            try:
                process_workflows(db_conn, conversation_id, user, ai_json)
            except Exception as e:
                logger.error(f"Error in process_workflows: {str(e)}\n{traceback.format_exc()}")
                # Continue execution even if workflow processing fails

            # ========================================
            # 10. SEND RESPONSE
            # ========================================
            response_payload = {
                "conversation_id": conversation_id,
                "ai_response": ai_json,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            wati.send_message(user["whatsapp_id"], ai_json["message"])
            return success_response(response_payload)

        except Exception as e:
            logger.error(f"Unexpected error in lambda_handler: {str(e)}\n{traceback.format_exc()}")
            return error_response("An unexpected error occurred")

        finally:
            # Ensure database connection is always closed
            if db_conn:
                try:
                    db_conn.close()
                except Exception as e:
                    logger.error(f"Error closing database connection: {str(e)}\n{traceback.format_exc()}")
    
    except Exception as e:
        # Catch-all for any unhandled exceptions
        logger.critical(f"Critical error in lambda_handler: {str(e)}\n{traceback.format_exc()}")
        return error_response("A critical error occurred")

def process_workflows(db_conn, conversation_id, user, ai_json):
    """Process all AI-triggered workflows"""
    # 6. Process AI Actions
    action_result = process_ai_action(db_conn, conversation_id, user["id"], ai_json)
    if action_result:
        ai_json["data"].update(action_result)

    # 7. Handle Special Workflows
    if ai_json["flags"]["crisis_detected"]:
        handle_crisis_workflow(db_conn, conversation_id, user["id"], ai_json)

def process_ai_action(db_conn, conversation_id, user_id, ai_json):
    """
    Main action processor - routes to specific handlers based on action type
    Returns additional data to merge with AI response
    """
    action = ai_json["action"]
    
    action_handlers = {
        "initial_greeting": cm_handler.handle_initial_greeting,
        "general_purpose": cm_handler.handle_general_purpose,
        "switch_to_coaching": cm_handler.handle_switch_to_coaching,
        "switch_to_concierge": cm_handler.handle_switch_to_concierge,
        "start_sst_framework": pc_handler.handle_start_sst_framework,
        "coaching_session_complete": pc_handler.handle_coaching_session_complete,
        "collect_booking_info": cc_handler.handle_collect_booking_info,
        "data_collection_complete": cc_handler.handle_data_collection_complete,
        "send_to_clinics": cc_handler.handle_send_to_clinics,
    }
    
    handler = action_handlers.get(action, handle_general_action)
    return handler(db_conn, conversation_id, user_id, ai_json)

def success_response(data):
    """Format successful Lambda response"""
    return {
        "statusCode": 200,
        "body": json.dumps(data)
    }

def error_response(error_message):
    """Format error Lambda response"""
    return {
        "statusCode": 500,
        "body": json.dumps({"error": error_message})
    }