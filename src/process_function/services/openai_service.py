from pathlib import Path
import json
from datetime import datetime, timedelta

import pytz
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, APIConnectionError, RateLimitError, APIStatusError
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all

from config import OPENAI_API_KEY, logger

patch_all()

SYSTEM_PROMPT_TEMPLATE = Path(__file__).parent / "system_prompt_template.txt"

def default_serializer(obj: object) -> str:
    """Default serializer for datetime objects

    Args:
        obj (object): The object to serialize.

    Returns:
        str: The serialized object.
    """
    if isinstance(obj, (datetime, timedelta)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def construct_openai_prompt(parent_data: dict, children: list, message_history: str, user_message: str) -> str:
    """
    Constructs the detailed system and user prompt for the OpenAI API.
    
    Args:
        parent_data (dict): The parent data including trial status and session counts.
        children (list): The list of children associated with the parent.
        message_history (str): The message history.
        user_message (str): The user message.
    
    Returns:
        str: The constructed prompt.
    """
    # Load system prompt from file
    with open(SYSTEM_PROMPT_TEMPLATE, "r", encoding="utf-8") as file:
        system_prompt_template = file.read()

    # Build the children information string
    if children:
        children_info = ""
        for child in children:
            children_info += f"Name: {child['name']}, Date of Birth: {child['date_of_birth']}\n"
    else:
        children_info = "No children found."
    
    # Calculate trial remaining days
    trial_remaining_days = 30
    if parent_data["subscription_status"] == "trialing":
        trial_remaining_days = (datetime.now(pytz.utc) - parent_data["trial_start_date"]).days
    
    # Format the prompt using actual data
    system_prompt = system_prompt_template.format(
        parent_name=parent_data.get("full_name", "N/A"),
        parent_phone=parent_data.get("phone_number", "N/A"),
        parent_id=parent_data.get("id", "N/A"),
        current_mode=parent_data.get("current_mode", "N/A"),
        current_step=parent_data.get("current_step", "N/A"),
        subscription_status=parent_data.get("subscription_status", "N/A"),
        trial_remaining_days=trial_remaining_days,
        session_count=parent_data.get("session_count", 0),
        monthly_summary_offered=parent_data.get("monthly_summary_offered", False),
        monthly_summary_opted_in=parent_data.get("monthly_summary_opted_in", False),
        children_info=children_info,
        message_history=message_history,
        user_message=user_message
    )
    logger.debug(f"Constructed OpenAI prompt: {system_prompt}")
    
    return system_prompt

def log_retry_attempt(retry_state):
    """Log the retry attempt details."""
    logger.warning(
        f"Retrying OpenAI call (attempt {retry_state.attempt_number}) "
        f"due to: {retry_state.outcome.exception()}"
    )

RETRYABLE_EXCEPTIONS = (
    APIConnectionError, # Network unreachable
    RateLimitError,     # 429 Too Many Requests
    APIStatusError,     # 5xx OpenAI server error
)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    before_sleep=log_retry_attempt
)
def call_openai_api(prompt: str) -> dict:
    """
    Calls the OpenAI Chat Completions API with the constructed prompt.
    Implements retry logic for transient errors with exponential backoff.

    Args:
        prompt (str): The prompt to call the OpenAI API with.

    Returns:
        dict: The response from the OpenAI API.

    Raises:
        Exception: If all retry attempts are exhausted or a non-retryable error occurs.
    """
    try:
        logger.info(f"Calling OpenAI API (attempt {call_openai_api.retry.statistics.get('attempt_number', 1)})")
        openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=30.0)
        response = openai_client.chat.completions.create(
            model="gpt-4.1", # Use a model that supports JSON mode
            messages=[
                {"role": "system", "content": prompt}
            ],
            response_format={"type": "json_object"},
        )
        response_content = response.choices[0].message.content
        logger.info(f"OpenAI response received: {response_content}")

        try:
            return json.loads(response_content)
        except json.JSONDecodeError as json_err:
            logger.error(f"OpenAI returned a non-JSON response: {response_content}. Error: {json_err}")
            # Should not retry on JSON decode error
            raise ValueError("OpenAI response is not valid JSON") from json_err

    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        logger.error(f"A retriable error occurred with OpenAI API: {e}")
        raise # Let tenacity catch and retry
    except Exception as e:
        logger.error(f"An unhandled error occurred while calling OpenAI API: {e}")
        # Other exceptions (e.g., AuthenticationError) should not be retried
        raise