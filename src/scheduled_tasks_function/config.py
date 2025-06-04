import json
import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Environment Variables & Secrets ---
APPLICATION_SECRETS_ARN = os.environ.get('APPLICATION_SECRETS_ARN') # ARN của Secret JSON

secrets_client = boto3.client('secretsmanager')

def get_secret(secret_arn: str) -> dict:
    try:
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        logger.info(f"Response: {response} {type(response)}")
        if 'SecretString' in response:
            return json.loads(response['SecretString'])
        else:
            # Xử lý binary secret nếu cần
            return json.loads(response['SecretBinary'].decode('utf-8'))
    except Exception as e:
        logger.error(f"Error getting secret {secret_arn}: {e}")
        raise

def load_app_config() -> dict:
    try:
        logger.info(f"Loading application configuration from Secrets Manager: {APPLICATION_SECRETS_ARN}")
        return get_secret(APPLICATION_SECRETS_ARN)
    except Exception as e:
        logger.error(f"Failed to load application configuration: {e}")
        raise RuntimeError(f"Could not load application configuration from {APPLICATION_SECRETS_ARN}") from e

app_conf = load_app_config()