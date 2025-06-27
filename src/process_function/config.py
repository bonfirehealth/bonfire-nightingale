import json
import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if os.environ.get("ENVIRONMENT_NAME") == "dev" else logging.INFO)

# --- Environment Variables & Secrets ---
DB_CREDENTIALS_SECRET_ARN = os.environ.get("DB_CREDENTIALS_SECRET_ARN")
APPLICATION_SECRETS_ARN = os.environ.get("APPLICATION_SECRETS_ARN") # ARN of Secret JSON

secrets_client = boto3.client("secretsmanager")

def get_secret(secret_arn: str) -> dict:
    """Get a secret from AWS Secrets Manager.

    Args:
        secret_arn (str): The ARN of the secret.

    Returns:
        dict: The secret.
    """
    try:
        logger.info(f"Fetching secret {secret_arn}")
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        if "SecretString" in response:
            return json.loads(response["SecretString"])
        else:
            # Handle binary secret if needed
            return json.loads(response["SecretBinary"].decode("utf-8"))
    except Exception as e:
        logger.error(f"Error getting secret {secret_arn}: {e}")
        raise


db_credentials = get_secret(DB_CREDENTIALS_SECRET_ARN)
app_conf = get_secret(APPLICATION_SECRETS_ARN)

# --- Database ---
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_NAME = os.environ.get("DB_NAME")
DB_USER = db_credentials.get("username")
DB_PASSWORD = db_credentials.get("password")

# --- OpenAI ---
OPENAI_API_KEY = app_conf.get("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = app_conf.get("OPENAI_ASSISTANT_ID")

# --- WATI ---
WATI_API_ENDPOINT = app_conf.get("WATI_API_ENDPOINT")
WATI_ACCESS_TOKEN = app_conf.get("WATI_ACCESS_TOKEN")

# --- Google ---
GOOGLE_EMAIL_ADDRESS = app_conf.get("GOOGLE_EMAIL_ADDRESS")
GOOGLE_APP_PASSWORD = app_conf.get("GOOGLE_APP_PASSWORD")
ESCALATION_EMAIL_RECIPIENTS = app_conf.get("ESCALATION_EMAIL_RECIPIENTS")
ESCALATION_EMAIL_CC = app_conf.get("ESCALATION_EMAIL_CC")
ESCALATION_EMAIL_SUBJECT = app_conf.get("ESCALATION_EMAIL_SUBJECT")

# --- Booking Confirmation ---
BOOKING_CONFIRMATION_EMAIL_RECIPIENTS = app_conf.get("BOOKING_CONFIRMATION_EMAIL_RECIPIENTS")
BOOKING_CONFIRMATION_EMAIL_CC = app_conf.get("BOOKING_CONFIRMATION_EMAIL_CC")
BOOKING_CONFIRMATION_EMAIL_SUBJECT = app_conf.get("BOOKING_CONFIRMATION_EMAIL_SUBJECT")

# --- Scheduler ---
NUDGE_EXECUTOR_LAMBDA_ARN = os.environ.get("NUDGE_EXECUTOR_LAMBDA_ARN")
EVENTBRIDGE_SCHEDULER_ROLE_ARN = os.environ.get("EVENTBRIDGE_SCHEDULER_ROLE_ARN")
SCHEDULE_GROUP_NAME = os.environ.get("SCHEDULE_GROUP_NAME")

# --- Voice Scheduler ---
VOICE_PROXY_EXECUTOR_LAMBDA_ARN = os.environ.get("VOICE_PROXY_EXECUTOR_LAMBDA_ARN")
EVENTBRIDGE_VOICE_SCHEDULER_ROLE_ARN = os.environ.get("EVENTBRIDGE_VOICE_SCHEDULER_ROLE_ARN")
VOICE_SCHEDULE_GROUP_NAME = os.environ.get("VOICE_SCHEDULE_GROUP_NAME")
VOICE_CALL_DOMAIN = app_conf.get("VOICE_CALL_DOMAIN")

# --- Elevenlabs ---
ELEVENLABS_API_KEY = app_conf.get("ELEVENLABS_API_KEY")
ELEVENLABS_AGENT_ID = app_conf.get("ELEVENLABS_AGENT_ID")
ELEVENLABS_WEBHOOK_SECRET = app_conf.get("ELEVENLABS_WEBHOOK_SECRET")

# --- Twilio ---
TWILIO_PHONE_NUMBER = app_conf.get("TWILIO_PHONE_NUMBER")
TWILIO_ACCOUNT_SID = app_conf.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = app_conf.get("TWILIO_AUTH_TOKEN")

# --- WTW Parent Handbook ---
WTW_PARENT_HANDBOOK_URL = app_conf.get("WTW_PARENT_HANDBOOK_URL")

# --- Stripe ---
STRIPE_SECRET_KEY = app_conf.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SUCCESS_URL = app_conf.get("STRIPE_WEBHOOK_SUCCESS_URL")
STRIPE_WEBHOOK_CANCEL_URL = app_conf.get("STRIPE_WEBHOOK_CANCEL_URL")
STRIPE_MONTHLY_PRICE_ID = app_conf.get("STRIPE_MONTHLY_PRICE_ID")
STRIPE_YEARLY_PRICE_ID = app_conf.get("STRIPE_YEARLY_PRICE_ID")

# --- System Prompt ---
SYSTEM_PROMPT = ""