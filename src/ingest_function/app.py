import json
import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs_client = boto3.client('sqs')
QUEUE_URL = os.environ.get('MESSAGE_QUEUE_URL')

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