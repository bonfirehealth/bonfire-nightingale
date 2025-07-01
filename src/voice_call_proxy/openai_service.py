from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI
from openai import APIConnectionError, RateLimitError, APIStatusError
import json
from config import logger, OPENAI_API_KEY

def construct_openai_prompt(call_history: str) -> str:
    """
    """
    with open("post_call_system_prompt.txt", "r") as f:
        system_prompt_template = f.read()
    return system_prompt_template.format(
        call_history=call_history
    )


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