import json
import logging
from workflow_handlers import handle_3_day_follow_up, handle_monthly_summary

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info(f"Scheduled task triggered with event: {json.dumps(event)}")
    
    task_type = event.get("task_type")

    if task_type == "3_DAY_FOLLOW_UP":
        handle_3_day_follow_up()
    elif task_type == "MONTHLY_SUMMARY":
        handle_monthly_summary()
    else:
        logger.warning(f"Unknown task type: {task_type}")

    return {
        'statusCode': 200,
        'body': json.dumps({'message': f'Task {task_type} processed.'})
    }