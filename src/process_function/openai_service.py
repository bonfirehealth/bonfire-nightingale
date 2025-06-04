import json
import logging
import requests
import time
from config import app_conf

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- OpenAI Client Class ---
class OpenAIClient:
    def __init__(self, api_key: str, api_base: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.api_base = api_base
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "assistants=v2"
        }

    def create_thread(self):
        url = f"{self.api_base}/threads"
        logger.info("Creating new OpenAI thread...")
        response = requests.post(url, headers=self.headers, json={})
        response.raise_for_status()
        thread_data = response.json()
        logger.info(f"OpenAI thread created: {thread_data.get('id')}")
        return thread_data

    def add_message_to_thread(self, thread_id: str, content: str, role: str = "user"):
        url = f"{self.api_base}/threads/{thread_id}/messages"
        payload = {"role": role, "content": content}
        logger.info(f"Adding message to thread {thread_id}: Role: {role}, Content: '{content[:50]}...'")
        response = requests.post(url, headers=self.headers, json=payload)
        logger.info(f"Add message response status: {response.status_code}")
        # logger.debug(f"Add message response content: {response.text}") # Log chi tiết nếu cần debug
        response.raise_for_status()
        return response.json()

    def create_run(self, thread_id: str, assistant_id: str, instructions: str = None): # Thêm instructions nếu cần
        url = f"{self.api_base}/threads/{thread_id}/runs"
        payload = {"assistant_id": assistant_id}
        if instructions:
            payload["instructions"] = instructions # Override instructions của Assistant cho Run này
        logger.info(f"Creating run for thread {thread_id} with assistant {assistant_id}")
        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()
        run_data = response.json()
        logger.info(f"Run created: {run_data.get('id')}, Status: {run_data.get('status')}")
        return run_data

    def retrieve_run(self, thread_id: str, run_id: str):
        url = f"{self.api_base}/threads/{thread_id}/runs/{run_id}"
        logger.debug(f"Retrieving run {run_id} for thread {thread_id}")
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def list_messages_from_thread(self, thread_id: str, limit: int = 1, order: str = "desc"):
        # Lấy message mới nhất từ assistant
        url = f"{self.api_base}/threads/{thread_id}/messages?limit={limit}&order={order}"
        logger.info(f"Listing messages for thread {thread_id} (limit {limit}, order {order})")
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

openai_client_instance = None

def get_openai_client_instance() -> OpenAIClient:
    global openai_client_instance
    if openai_client_instance is None:
        openai_api_key = app_conf.get('OPENAI_API_KEY')
        if not openai_api_key:
            raise ValueError("OpenAI API key not found or not configured in application secrets.")
        openai_client_instance = OpenAIClient(api_key=openai_api_key)
    return openai_client_instance

def call_openai_assistant(
    current_db_conversation_id: int,
    db_openai_thread_id: str,
    user_name: str,
    user_message_text: str,
    current_sst_step: str,
    db_conn
    ) -> dict:
    client = get_openai_client_instance()
    assistant_id = app_conf.get("OPENAI_ASSISTANT_ID")
    if not assistant_id:
        raise ValueError("OPENAI_ASSISTANT_ID not configured in application secrets.")

    active_thread_id = db_openai_thread_id

    try:
        # 1. Create a new thread if one doesn't exist for this conversation
        if not active_thread_id:
            thread_response = client.create_thread()
            active_thread_id = thread_response.get("id")
            if not active_thread_id:
                logger.error("Failed to create or retrieve thread ID from OpenAI.")
                return {"action_type": "ERROR", "error_message": "Failed to initialize AI conversation thread."}
            # Lưu thread_id mới vào DB
            import database
            database.update_conversation_with_thread_id(db_conn, current_db_conversation_id, active_thread_id)
            logger.info(f"Associated new OpenAI thread {active_thread_id} with DB conversation {current_db_conversation_id}")

        # 2. Add the user's message to the thread
        content = f"{user_name}: {user_message_text}"
        client.add_message_to_thread(thread_id=active_thread_id, content=content, role="user")

        # 3. Create a Run
        run_response = client.create_run(thread_id=active_thread_id, assistant_id=assistant_id)
        run_id = run_response.get("id")
        if not run_id:
            logger.error("Failed to create run.")
            return {"action_type": "ERROR", "error_message": "Failed to start AI processing."}

        # 4. Poll for Run completion
        start_time = time.time()
        timeout_seconds = 60
        while time.time() - start_time < timeout_seconds:
            run_status_response = client.retrieve_run(thread_id=active_thread_id, run_id=run_id)
            status = run_status_response.get("status")
            logger.info(f"Run {run_id} status: {status}")

            if status == "completed":
                break
            elif status in ["queued", "in_progress", "requires_action"]: # requires_action cho Function calling
                time.sleep(2)  # Chờ 2 giây trước khi kiểm tra lại
            else: # failed, cancelled, expired
                logger.error(f"Run {run_id} failed or ended unexpectedly. Status: {status}. Details: {run_status_response}")
                error_detail = run_status_response.get("last_error", {}).get("message", "AI processing failed.")
                return {"action_type": "ERROR", "error_message": f"AI processing error: {error_detail}"}
        else: # Vòng lặp timeout
            logger.error(f"Run {run_id} timed out after {timeout_seconds} seconds.")
            return {"action_type": "ERROR", "error_message": "AI processing timed out."}

        # 5. Retrieve the latest assistant's message from the thread
        messages_response = client.list_messages_from_thread(thread_id=active_thread_id, limit=1, order="desc")
        
        if not messages_response.get("data"):
            logger.error(f"No messages returned from assistant for thread {active_thread_id} after run completion.")
            return {"action_type": "ERROR", "error_message": "AI did not provide a response."}

        latest_message = messages_response["data"][0]
        if latest_message.get("role") != "assistant":
            logger.warning(f"Latest message is not from assistant. Role: {latest_message.get('role')}. Trying next message.")
            # Có thể cần logic phức tạp hơn ở đây nếu có nhiều tool_calls messages
            if len(messages_response["data"]) > 1 and messages_response["data"][1].get("role") == "assistant":
                latest_message = messages_response["data"][1]
            else:
                logger.error(f"Could not find a recent assistant message in thread {active_thread_id}.")
                return {"action_type": "ERROR", "error_message": "AI response structure unexpected."}

        assistant_response_content = ""
        for content_block in latest_message.get("content", []):
            if content_block.get("type") == "text":
                assistant_response_content = content_block.get("text", {}).get("value", "")
                break # Giả sử chỉ có 1 text block chứa JSON

        if not assistant_response_content:
            logger.error(f"Assistant message content is empty or not text for thread {active_thread_id}.")
            return {"action_type": "ERROR", "error_message": "AI response content missing."}

        logger.info(f"Raw JSON string from assistant: {assistant_response_content}")
        ai_json_response = json.loads(assistant_response_content)
        return ai_json_response

    except requests.exceptions.HTTPError as http_err:
        logger.error(f"OpenAI API HTTP error: {http_err} - Response: {http_err.response.text}", exc_info=True)
        error_message = "Error communicating with AI service."
        try:
            err_details = http_err.response.json()
            error_message = err_details.get("error", {}).get("message", error_message)
        except: #pylint: disable=bare-except
            pass
        return {"action_type": "ERROR", "error_message": error_message}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response from OpenAI: {e}. Response string: '{assistant_response_content}'", exc_info=True)
        return {"action_type": "ERROR", "error_message": "AI response format error."}
    except Exception as e:
        logger.error(f"Unexpected error in call_openai_assistant: {e}", exc_info=True)
        return {"action_type": "ERROR", "error_message": "An internal error occurred while contacting the AI."}