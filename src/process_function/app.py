import json
import logging
import psycopg2
import database
import openai_service
import wati_service
import workflow_handlers
from config import app_conf

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info(f"Received SQS event in {app_conf.get('ENVIRONMENT_NAME')}: {json.dumps(event, indent=2)}")
    
    # Load config một lần (config.py sẽ cache)
    db_conn = None

    for record in event.get('Records', []):
        try:
            # parse WATI payload
            wati_payload_str = record.get("body")
            if not wati_payload_str:
                logger.error("SQS record has no body.")
                continue

            wati_payload = json.loads(wati_payload_str)
            user_id = wati_payload.get("waId")
            user_message_text = wati_payload.get("text")
            user_name = wati_payload.get("senderName")

            logger.info(f"Received message from {user_name} ({user_id}): {user_message_text}")

            db_conn = database.get_db_connection()
            database.get_or_create_user(db_conn, user_id, user_name)

            # 1. Get/Create Conversation
            conversation = database.get_active_conversation_state(db_conn, user_id) or \
                           database.create_new_conversation(db_conn, user_id)
            current_conversation_id = conversation["conversation_id"]
            current_conversation_state_json = conversation.get("state_json", {"history": []})

            # 2. Prepare for and Call OpenAI
            if not current_conversation_state_json.get("history"):
                current_conversation_state_json["history"] = []
            current_conversation_state_json["history"].append({"role": "user", "content": user_message_text})
            ai_json_response = openai_service.call_openai_assistant(
                current_conversation_id,
                conversation.get("openai_thread_id"),
                user_name,
                user_message_text,
                conversation.get("current_sst_step"),
                db_conn
            )

            # 3. Process AI Response
            # process_ai_response sẽ chứa logic phức tạp để quyết định next_step, new_state, is_active
            # và gọi các service (wati, db) để thực hiện actions.
            processed_results = workflow_handlers.process_ai_response(
                db_conn, user_id, current_conversation_id, current_conversation_state_json, ai_json_response
            )
            
            # 4. Update conversation state in DB
            # processed_results sẽ chứa next_sst_step, new_state_for_db, is_conversation_active
            if processed_results:
                 # Giới hạn history trước khi lưu
                if "history" in processed_results["new_state_for_db"]:
                    processed_results["new_state_for_db"]["history"] = processed_results["new_state_for_db"]["history"][-20:]

                database.update_conversation_state(
                    db_conn, current_conversation_id,
                    processed_results["next_sst_step"],
                    processed_results["new_state_for_db"],
                    is_active=processed_results["is_conversation_active"]
                )

        except psycopg2.Error as db_err: # Lỗi DB cụ thể
            logger.error(f"Database error processing SQS record: {db_err}", exc_info=True)
            if db_conn: db_conn.rollback() # Quan trọng: rollback nếu có lỗi DB
            # Quyết định có re-queue message không (bằng cách raise error lại)
            # Hoặc nếu lỗi là tạm thời, có thể không raise để SQS tự retry sau visibility timeout
            # Nếu lỗi nghiêm trọng, message sẽ vào DLQ sau vài lần retry
            # raise db_err # Để SQS retry
        except Exception as e:
            logger.error(f"Generic error processing SQS record: {e}", exc_info=True)
            if db_conn and not db_conn.closed: db_conn.rollback()
            # raise e # Để SQS retry
        finally:
            # Quản lý db_conn
            pass
    
    if db_conn and not db_conn.closed:
        db_conn.close()
        logger.info("DB connection closed at the end of Lambda invocation.")
        db_conn = None
            
    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Message processed successfully'})
    }