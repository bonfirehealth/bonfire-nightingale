import os
import json
import uuid
from datetime import datetime, timezone, timedelta

import boto3

from config import (
    logger, NUDGE_EXECUTOR_LAMBDA_ARN, EVENTBRIDGE_SCHEDULER_ROLE_ARN, SCHEDULE_GROUP_NAME,
    TWILIO_PHONE_NUMBER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
    ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, ELEVENLABS_WEBHOOK_SECRET,
)

scheduler_client = boto3.client('scheduler')
ssm_client = boto3.client('ssm')

def create_trial_schedules(whatsapp_id: str, coaching_session_id: int) -> None:
    """Create a set of schedules on EventBridge for the user's trial.

    Args:
        whatsapp_id (str): The ID of the user.
        coaching_session_id (int): The ID of the coaching session.
    """
    if not NUDGE_EXECUTOR_LAMBDA_ARN or not EVENTBRIDGE_SCHEDULER_ROLE_ARN:
        logger.error("Lambda environment variables for scheduler are not set!")
        raise ValueError("Scheduler configuration missing.")

    # UTC time currently
    now_utc = datetime.now(timezone.utc)

    # Define the nudge and activation time (in days)
    schedules_to_create = [
        {"name": "day-7-nudge", "days": 7, "type": "nudge_day_7_soft_introduction"},
        {"name": "day-14-nudge", "days": 14, "type": "nudge_day_14_low_usage"},
        {"name": "day-20-conversion", "days": 20, "type": "nudge_day_20_conversion"},
        {"name": "day-28-reminder", "days": 28, "type": "nudge_day_28_final_reminder"},
        {"name": "day-30-expiry", "days": 30, "type": "trial_expiry"},
    ]

    logger.info(f"Creating trial schedules for user {whatsapp_id}")

    for schedule_info in schedules_to_create:
        schedule_name = f"{schedule_info['name']}-{whatsapp_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        schedule_time = now_utc + timedelta(days=schedule_info['days'])
        # schedule_time = now_utc + timedelta(minutes=5 + schedule_info['days'] // 7)
        
        # Time format: at(yyyy-mm-ddThh:mm:ss)
        schedule_expression = f"at({schedule_time.strftime('%Y-%m-%dT%H:%M:%S')})"
        
        # Payload will be sent to Lambda Executor
        payload = json.dumps({
            "waId": whatsapp_id,
            "coachingSessionId": coaching_session_id,
            "nudgeType": schedule_info['type']
        })

        try:
            scheduler_client.create_schedule(
                Name=schedule_name,
                GroupName=SCHEDULE_GROUP_NAME,
                ScheduleExpression=schedule_expression,
                ScheduleExpressionTimezone="UTC",
                Target={
                    'Arn': NUDGE_EXECUTOR_LAMBDA_ARN,
                    'RoleArn': EVENTBRIDGE_SCHEDULER_ROLE_ARN,
                    'Input': payload,
                },
                FlexibleTimeWindow={'Mode': 'OFF'},
                ActionAfterCompletion='DELETE'
            )
            logger.info(f"Successfully created schedule: {schedule_name} at {schedule_expression}")
        except Exception as e:
            logger.error(f"Failed to create schedule {schedule_name} for user {whatsapp_id}. Error: {e}")
            # Add logic to retry or send a notification to the dev team
            raise e

def schedule_single_event(whatsapp_id: str, coaching_session_id: int | None, event_type: str, days_from_now: int):
    """Schedule a single event on EventBridge Scheduler.

    Args:
        whatsapp_id (str): The ID of the user.
        coaching_session_id (int): The ID of the coaching session.
        event_type (str): The type of the event.
        days_from_now (int): The number of days from now to schedule the event.
    """
    now_utc = datetime.now(timezone.utc)
    schedule_time = now_utc + timedelta(days=days_from_now) - timedelta(minutes=15)
    # schedule_time = now_utc + timedelta(minutes=5 + days_from_now // 10)
    schedule_expression = f"at({schedule_time.strftime('%Y-%m-%dT%H:%M:%S')})"
    
    # Create a unique name for the schedule to avoid conflicts and manage it easily
    schedule_name = f"{event_type}-{whatsapp_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    payload = json.dumps({
        "waId": whatsapp_id,
        "coachingSessionId": coaching_session_id,
        "nudgeType": event_type
    })

    try:
        scheduler_client.create_schedule(
            Name=schedule_name,
            GroupName=SCHEDULE_GROUP_NAME,
            ScheduleExpression=schedule_expression,
            ScheduleExpressionTimezone="UTC",
            Target={
                'Arn': NUDGE_EXECUTOR_LAMBDA_ARN,
                'RoleArn': EVENTBRIDGE_SCHEDULER_ROLE_ARN,
                'Input': payload,
            },
            FlexibleTimeWindow={'Mode': 'OFF'},
            ActionAfterCompletion='DELETE'
        )
        logger.info(f"Successfully created schedule: {schedule_name} at {schedule_expression}")
    except scheduler_client.exceptions.ConflictException:
        logger.warning(f"Schedule {schedule_name} already exists. Skipping creation.")
    except Exception as e:
        logger.error(f"Failed to create schedule {schedule_name}. Error: {e}")
        raise e

def schedule_voice_call(parent_id: int, target_phone: str, voice_call_id: int, delay_minutes: int = 1):
    """
    Schedule a voice call for the parent.
    
    Args:
        parent_id (int): The ID of the parent.
        target_phone (str): The phone number of the target.
        voice_call_id (int): The ID of the voice call.
        delay_minutes (int): The number of minutes to delay the call.
    """
    # Get config from SSM
    dynamic_config = get_voice_proxy_config_from_ssm()
    VOICE_SCHEDULER_ROLE_ARN = os.getenv("VOICE_SCHEDULER_ROLE_ARN")
    VOICE_SCHEDULE_GROUP_NAME = os.getenv("VOICE_SCHEDULE_GROUP_NAME")
    VOICE_CLUSTER_ARN = dynamic_config['cluster-arn']
    VOICE_TASK_DEFINITION_ARN = dynamic_config['task-def-arn']
    VOICE_SUBNET_ID = dynamic_config['subnet-id']

    logger.debug(f"VOICE_CLUSTER_ARN: {VOICE_CLUSTER_ARN}")
    logger.debug(f"VOICE_TASK_DEFINITION_ARN: {VOICE_TASK_DEFINITION_ARN}")
    logger.debug(f"VOICE_SCHEDULER_ROLE_ARN: {VOICE_SCHEDULER_ROLE_ARN}")
    logger.debug(f"VOICE_SCHEDULE_GROUP_NAME: {VOICE_SCHEDULE_GROUP_NAME}")
    logger.debug(f"VOICE_SUBNET_ID: {VOICE_SUBNET_ID}")
    logger.debug(f"TWILIO_PHONE_NUMBER: {TWILIO_PHONE_NUMBER}")
    logger.debug(f"TWILIO_ACCOUNT_SID: {TWILIO_ACCOUNT_SID}")
    logger.debug(f"TWILIO_AUTH_TOKEN: {TWILIO_AUTH_TOKEN}")

    if not VOICE_CLUSTER_ARN:
        logger.error("VOICE_CLUSTER_ARN is not set!")
        raise ValueError("VOICE_CLUSTER_ARN is not set!")

    if not VOICE_TASK_DEFINITION_ARN:
        logger.error("VOICE_TASK_DEFINITION_ARN is not set!")
        raise ValueError("VOICE_TASK_DEFINITION_ARN is not set!")
    
    if not VOICE_SCHEDULER_ROLE_ARN:
        logger.error("VOICE_SCHEDULER_ROLE_ARN is not set!")
        raise ValueError("VOICE_SCHEDULER_ROLE_ARN is not set!")
    
    if not VOICE_SCHEDULE_GROUP_NAME:
        logger.error("VOICE_SCHEDULE_GROUP_NAME is not set!")
        raise ValueError("VOICE_SCHEDULE_GROUP_NAME is not set!")
    
    if not VOICE_SUBNET_ID:
        logger.error("VOICE_SUBNET_ID is not set!")
        raise ValueError("VOICE_SUBNET_ID is not set!")
    
    if not TWILIO_PHONE_NUMBER:
        logger.error("TWILIO_PHONE_NUMBER is not set!")
        raise ValueError("TWILIO_PHONE_NUMBER is not set!")
    
    if not TWILIO_ACCOUNT_SID:
        logger.error("TWILIO_ACCOUNT_SID is not set!")
        raise ValueError("TWILIO_ACCOUNT_SID is not set!")
    
    if not TWILIO_AUTH_TOKEN:
        logger.error("TWILIO_AUTH_TOKEN is not set!")
        raise ValueError("TWILIO_AUTH_TOKEN is not set!")

    now_utc = datetime.now(timezone.utc)
    schedule_time = now_utc + timedelta(minutes=delay_minutes)
    schedule_expression = f"at({schedule_time.strftime('%Y-%m-%dT%H:%M:%S')})"
    
    # Create a unique name for the schedule to avoid conflicts and manage it easily
    schedule_name = f"voice-call-{parent_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Payload will be sent to Lambda Executor
    fargate_input = {
        "containerOverrides": [{
            "name": "VoiceProxyContainer",
            "environment": [
                {"name": "TARGET_PHONE", "value": target_phone},
                {"name": "TWILIO_PHONE_NUMBER", "value": TWILIO_PHONE_NUMBER},
                {"name": "TWILIO_ACCOUNT_SID", "value": TWILIO_ACCOUNT_SID},
                {"name": "TWILIO_AUTH_TOKEN", "value": TWILIO_AUTH_TOKEN},
                {"name": "ELEVENLABS_API_KEY", "value": ELEVENLABS_API_KEY},
                {"name": "ELEVENLABS_AGENT_ID", "value": ELEVENLABS_AGENT_ID},
                {"name": "ELEVENLABS_WEBHOOK_SECRET", "value": ELEVENLABS_WEBHOOK_SECRET},
                {"name": "VOICE_CALL_ID", "value": str(voice_call_id)},
            ]
        }]
    }
    logger.debug(f"Fargate input: {fargate_input}")
    
    logger.info(f"Offering voice call to parent {parent_id}")

    try:
        scheduler_client.create_schedule(
            Name=schedule_name,
            GroupName=VOICE_SCHEDULE_GROUP_NAME,
            ScheduleExpression=schedule_expression,
            ScheduleExpressionTimezone="UTC",
            Target={
                "Arn": VOICE_CLUSTER_ARN, # Target is ECS Cluster
                "RoleArn": VOICE_SCHEDULER_ROLE_ARN,
                "Input": json.dumps(fargate_input),
                "EcsParameters": {
                    "TaskDefinitionArn": VOICE_TASK_DEFINITION_ARN,
                    "LaunchType": "FARGATE",
                    "NetworkConfiguration": {
                        "awsvpcConfiguration": {
                            "Subnets": [VOICE_SUBNET_ID],
                            "AssignPublicIp": "ENABLED"
                        }
                    }
                }
            },
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE" # Auto delete schedule after running
        )
    except scheduler_client.exceptions.ConflictException:
        logger.warning(f"Schedule {schedule_name} already exists. Skipping creation.")
    except Exception as e:
        logger.error(f"Failed to create schedule {schedule_name}. Error: {e}")
        raise e

_cached_voice_config = None

def get_voice_proxy_config_from_ssm():
    """Chỉ lấy các config động từ SSM."""
    global _cached_voice_config
    if _cached_voice_config:
        return _cached_voice_config
    
    VOICE_PROXY_CONFIG_PATH = os.getenv("VOICE_PROXY_CONFIG_PATH")
    if not VOICE_PROXY_CONFIG_PATH:
        raise ValueError("VOICE_PROXY_CONFIG_PATH is not set!")

    response = ssm_client.get_parameters_by_path(
        Path=VOICE_PROXY_CONFIG_PATH,
        Recursive=False,
        WithDecryption=True
    )
    params = {p['Name'].split('/')[-1]: p['Value'] for p in response['Parameters']}
    _cached_voice_config = params
    return _cached_voice_config