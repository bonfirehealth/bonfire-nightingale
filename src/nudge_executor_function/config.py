import json
import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if os.environ.get("ENVIRONMENT_NAME") == "dev" else logging.INFO)

# --- Environment Variables & Secrets ---
DB_CREDENTIALS_SECRET_ARN = os.environ.get("DB_CREDENTIALS_SECRET_ARN")
APPLICATION_SECRETS_ARN = os.environ.get("APPLICATION_SECRETS_ARN") # ARN của Secret JSON

secrets_client = boto3.client("secretsmanager")

def get_secret(secret_arn: str) -> dict:
    try:
        logger.info(f"Fetching secret {secret_arn}")
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        if "SecretString" in response:
            return json.loads(response["SecretString"])
        else:
            # Xử lý binary secret nếu cần
            return json.loads(response["SecretBinary"].decode("utf-8"))
    except Exception as e:
        logger.error(f"Error getting secret {secret_arn}: {e}")
        raise


db_credentials = get_secret(DB_CREDENTIALS_SECRET_ARN)
app_conf = get_secret(APPLICATION_SECRETS_ARN)

DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_NAME = os.environ.get("DB_NAME")
DB_USER = db_credentials.get("username")
DB_PASSWORD = db_credentials.get("password")

OPENAI_API_KEY = app_conf.get("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = app_conf.get("OPENAI_ASSISTANT_ID")

WATI_API_ENDPOINT = app_conf.get("WATI_API_ENDPOINT")
WATI_ACCESS_TOKEN = app_conf.get("WATI_ACCESS_TOKEN")

GOOGLE_EMAIL_ADDRESS = app_conf.get("GOOGLE_EMAIL_ADDRESS")
GOOGLE_APP_PASSWORD = app_conf.get("GOOGLE_APP_PASSWORD")
ESCALATION_EMAIL_RECIPIENTS = app_conf.get("ESCALATION_EMAIL_RECIPIENTS")
ESCALATION_EMAIL_CC = app_conf.get("ESCALATION_EMAIL_CC")
ESCALATION_EMAIL_SUBJECT = app_conf.get("ESCALATION_EMAIL_SUBJECT")

BOOKING_CONFIRMATION_EMAIL_RECIPIENTS = app_conf.get("BOOKING_CONFIRMATION_EMAIL_RECIPIENTS")
BOOKING_CONFIRMATION_EMAIL_CC = app_conf.get("BOOKING_CONFIRMATION_EMAIL_CC")
BOOKING_CONFIRMATION_EMAIL_SUBJECT = app_conf.get("BOOKING_CONFIRMATION_EMAIL_SUBJECT")

WTW_PARENT_HANDBOOK_URL = app_conf.get("WTW_PARENT_HANDBOOK_URL")

SYSTEM_PROMPT = ""
with open("./system_prompt.txt", "r") as f:
    SYSTEM_PROMPT = f.read()