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

# --- Stripe ---
STRIPE_PUBLIC_KEY = app_conf.get("STRIPE_PUBLIC_KEY")
STRIPE_SECRET_KEY = app_conf.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = app_conf.get("STRIPE_WEBHOOK_SECRET")
