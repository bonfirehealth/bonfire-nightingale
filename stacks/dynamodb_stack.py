# stacks/dynamodb_stack.py

from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    RemovalPolicy,
    CfnOutput
)
from constructs import Construct

class DynamoDBStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        removal_policy = RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY

        self.active_users_table = dynamodb.Table(self, "ActiveUsersTable",
            table_name=f"Nightingale-ActiveUsers-{environment_name}",
            partition_key=dynamodb.Attribute(
                name="userId",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
            time_to_live_attribute="ttlTimestamp",
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES
        )

        self.metrics_table = dynamodb.Table(self, "MetricsTable",
            table_name=f"Nightingale-Metrics-{environment_name}",
            partition_key=dynamodb.Attribute(
                name="activeUserCount", # Ví dụ: "activeUserCount"
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy
        )

        CfnOutput(self, "ActiveUsersTableName",
            value=self.active_users_table.table_name
        )
        CfnOutput(self, "MetricsTableName",
            value=self.metrics_table.table_name
        )