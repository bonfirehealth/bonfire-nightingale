from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
    BundlingOptions,
    Duration
)
from constructs import Construct

class SchedulerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.IVpc,
                 lambda_security_group: ec2.ISecurityGroup,
                 db_cluster: rds.IDatabaseCluster,
                 db_credentials_secret: secretsmanager.ISecret,
                 application_secrets_arn: str,
                 db_name: str,
                 environment_name: str,
                 is_prod: bool,
                 lambda_memory_scheduled: int,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # IAM Role and Environment variables similar to ProcessFunction
        lambda_base_role = iam.Role(self, "ScheduledLambdaBaseRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )
        db_credentials_secret.grant_read(lambda_base_role)

        common_lambda_env = {
            "DB_HOST": db_cluster.cluster_endpoint.hostname,
            "DB_PORT": str(db_cluster.cluster_endpoint.port),
            "DB_NAME": db_name,
            "DB_CREDENTIALS_SECRET_ARN": db_credentials_secret.secret_arn,
            "APPLICATION_SECRETS_ARN": application_secrets_arn
        }

        # Lambda ScheduledTasksFunction
        scheduled_tasks_function = lambda_.Function(self, "ScheduledTasksFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="app.lambda_handler",
            code=lambda_.Code.from_asset("src/scheduled_tasks_function", bundling=BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                command=[
                    "bash", "-c", (
                        "pip install -r requirements.txt -t /asset-output && "
                        "cp -au . /asset-output"
                    )
                ]
            )),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[lambda_security_group],
            environment=common_lambda_env,
            role=lambda_base_role, # Use base role, can add specific policy if needed
            timeout=Duration.minutes(2),
            memory_size=256
        )

        # EventBridge Rule for 3-Day Follow-up (runs every hour to check)
        follow_up_rule = events.Rule(self, "FollowUpRule",
            schedule=events.Schedule.rate(Duration.hours(1)), # Runs every hour
            # schedule=events.Schedule.cron(minute="0", hour="*") # Or cron
            description="Rule to trigger 3-day follow-up checks"
        )
        follow_up_rule.add_target(targets.LambdaFunction(scheduled_tasks_function,
            event=events.RuleTargetInput.from_object({"task_type": "3_DAY_FOLLOW_UP"})
        ))

        # EventBridge Rule for Monthly Summary (runs on the 1st of every month at 00:00 UTC)
        monthly_summary_rule = events.Rule(self, "MonthlySummaryRule",
            schedule=events.Schedule.cron(
                minute="0",
                hour="0",
                day="1", # Day 1 of the month
                month="*",
                year="*"
            ),
            description="Rule to trigger monthly progress summary"
        )
        monthly_summary_rule.add_target(targets.LambdaFunction(scheduled_tasks_function,
            event=events.RuleTargetInput.from_object({"task_type": "MONTHLY_SUMMARY"})
        ))