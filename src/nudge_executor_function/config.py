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

WATI_API_ENDPOINT = app_conf.get("WATI_API_ENDPOINT")
WATI_ACCESS_TOKEN = app_conf.get("WATI_ACCESS_TOKEN")
