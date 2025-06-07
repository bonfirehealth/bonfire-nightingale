import os
import json
import boto3
from datetime import datetime, timezone, timedelta
from config import logger

scheduler_client = boto3.client('scheduler')
NUDGE_EXECUTOR_LAMBDA_ARN = os.environ.get("NUDGE_EXECUTOR_LAMBDA_ARN")
EVENTBRIDGE_SCHEDULER_ROLE_ARN = os.environ.get("EVENTBRIDGE_SCHEDULER_ROLE_ARN")
SCHEDULE_GROUP_NAME = os.environ.get("SCHEDULE_GROUP_NAME")

def create_trial_schedules(user_id: str):
    """
    Tạo một bộ các schedule trên EventBridge cho trial của người dùng.
    Mỗi schedule là một one-time event, và sẽ tự xóa sau khi hoàn thành.
    """
    if not NUDGE_EXECUTOR_LAMBDA_ARN or not EVENTBRIDGE_SCHEDULER_ROLE_ARN:
        logger.error("Lambda environment variables for scheduler are not set!")
        raise ValueError("Scheduler configuration missing.")

    # UTC time hiện tại
    now_utc = datetime.now(timezone.utc)

    # Định nghĩa các nudge và thời điểm kích hoạt (tính bằng ngày)
    schedules_to_create = [
        {"name": "day-7-nudge", "days": 7, "type": "nudge_day_7"},
        {"name": "day-14-nudge", "days": 14, "type": "nudge_day_14"},
        {"name": "day-20-conversion", "days": 20, "type": "nudge_day_20_conversion"},
        {"name": "day-28-reminder", "days": 28, "type": "nudge_day_28_reminder"},
        {"name": "day-30-expiry", "days": 30, "type": "trial_expiry"},
    ]

    logger.info(f"Creating trial schedules for user {user_id}")

    for schedule_info in schedules_to_create:
        schedule_name = f"{schedule_info['name']}-{user_id}"
        schedule_time = now_utc + timedelta(days=schedule_info['days'])
        
        # Định dạng thời gian cho ScheduleExpression của EventBridge: at(yyyy-mm-ddThh:mm:ss)
        schedule_expression = f"at({schedule_time.strftime('%Y-%m-%dT%H:%M:%S')})"
        
        # Payload sẽ được gửi tới Lambda Executor
        payload = json.dumps({
            "userId": user_id,
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
                # Tự động xóa schedule sau khi nó đã chạy xong, rất tiện lợi!
                ActionAfterCompletion='DELETE'
            )
            logger.info(f"Successfully created schedule: {schedule_name} at {schedule_expression}")
        except Exception as e:
            logger.error(f"Failed to create schedule {schedule_name} for user {user_id}. Error: {e}")
            # Ở đây bạn có thể thêm logic để retry hoặc gửi thông báo cho đội dev
            # Vì đây là một phần quan trọng, nếu thất bại, nên được ghi nhận lại
            # Trong trường hợp này, chúng ta sẽ throw exception để transaction DB được rollback
            raise e

def schedule_single_event(user_id: str, conversation_id: str, event_type: str, days_from_now: int):
    """
    Hàm helper để tạo một schedule one-time trên EventBridge Scheduler.
    """
    now_utc = datetime.now(timezone.utc)
    schedule_time = now_utc + timedelta(days=days_from_now)
    schedule_expression = f"at({schedule_time.strftime('%Y-%m-%dT%H:%M:%S')})"
    
    # Tạo một tên duy nhất để tránh xung đột và có thể quản lý được
    # Dùng conversation_id để đảm bảo duy nhất cho mỗi lần follow-up
    schedule_name = f"{event_type}-{conversation_id}"

    payload = json.dumps({
        "userId": user_id,
        "conversationId": conversation_id, # Thêm conversationId vào payload
        "nudgeType": event_type # Dùng lại key 'nudgeType' cho nhất quán
    })

    try:
        scheduler_client.create_schedule(
            Name=schedule_name,
            GroupName=SCHEDULE_GROUP_NAME, # Tái sử dụng group đã có
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
        raise e # Ném lỗi ra ngoài để hàm gọi có thể xử lý