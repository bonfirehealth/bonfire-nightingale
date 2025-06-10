import json
import os
import time
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs_client = boto3.client('sqs')
dynamodb = boto3.resource('dynamodb')
ACTIVE_USERS_TABLE_NAME = os.environ.get('ACTIVE_USERS_TABLE_NAME')
QUEUE_URL = os.environ.get('MESSAGE_QUEUE_URL')

# Active session timeout
SESSION_TIMEOUT_SECONDS = 5 * 60

def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        # WATI thường gửi payload trong 'body' của HTTP POST request
        # API Gateway v2 (HTTP API) có thể parse JSON body tự động
        # Nếu body là string, cần json.loads(event.get('body', '{}'))
        message_payload_str = event.get('body')
        if not message_payload_str:
            logger.error("No body found in the event.")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing message body'})
            }
        
        # Giả sử body là một JSON string
        message_payload = json.loads(message_payload_str)
        logger.info(f"Parsed WATI payload: {message_payload}")

        # Update active users table
        update_active_users_table(message_payload['waId'], message_payload.get('senderName', 'Unknown'))

        # Gửi message vào SQS
        sqs_client.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(message_payload) # Gửi toàn bộ payload của WATI
        )
        logger.info(f"Message sent to SQS: {QUEUE_URL}")

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Webhook received and queued'})
        }
    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError: {e} - Payload: {message_payload_str}")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid JSON in request body'})
        }
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }

def update_active_users_table(user_id: str, user_name: str):
    """
    Update active users table with user_id and TTL timestamp

    Args:
        user_id (str): User ID to update in the active users table
        user_name (str): User name to update in the active users table
    """
    try:
        table = dynamodb.Table(ACTIVE_USERS_TABLE_NAME)
        # Tính toán timestamp hết hạn (hiện tại + 5 phút)
        ttl_timestamp = int(time.time()) + SESSION_TIMEOUT_SECONDS

        table.put_item(
            Item={
                'userId': user_id,
                'userName': user_name,
                'ttlTimestamp': ttl_timestamp
            }
        )
        logger.info(f"Updated active users table for user: {user_id}")
    except Exception as e:
        logger.error(f"Error updating active users table: {e}", exc_info=True)