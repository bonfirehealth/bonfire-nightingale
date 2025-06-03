from aws_cdk import (
    Stack,
    aws_sqs as sqs,
    Duration,
    RemovalPolicy
)
from constructs import Construct

class MessagingStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Dead Letter Queue
        self.dead_letter_queue = sqs.Queue(self, "NightingaleMessageDLQ",
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.DESTROY if not is_prod else RemovalPolicy.RETAIN,
        )

        # Main SQS Queue
        self.message_queue = sqs.Queue(self, "NightingaleMessageQueue",
            visibility_timeout=Duration.minutes(5), # Thời gian xử lý message của Lambda
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3, # Số lần thử lại trước khi vào DLQ
                queue=self.dead_letter_queue
            ),
            removal_policy=RemovalPolicy.DESTROY if not is_prod else RemovalPolicy.RETAIN,
            # encryption=sqs.QueueEncryption.KMS_MANAGED # Bật mã hóa nếu cần
        )