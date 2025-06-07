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

class InterestCheckSchedulerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.IVpc, # Pass VPC if Lambda needs DB access
                 lambda_security_group: ec2.ISecurityGroup,
                 db_cluster: rds.IDatabaseCluster,
                 db_credentials_secret: secretsmanager.ISecret,
                 application_secrets_arn: str, # For WATI API if sending msgs directly
                 db_name: str,
                 environment_name: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # IAM Role for the Lambda
        interest_check_lambda_role = iam.Role(self, "InterestCheckLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            # ... managed policies for BasicExec, VPCAccess ...
        )
        db_credentials_secret.grant_read(interest_check_lambda_role)
        # Grant WATI secret access if sending messages directly
        application_secrets_object = secretsmanager.Secret.from_secret_complete_arn(self, "ImportedAppSecretsForInterestCheck", application_secrets_arn)
        application_secrets_object.grant_read(interest_check_lambda_role)

        interest_check_function = lambda_.Function(self, "InterestCheckFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="app.lambda_handler", # File app.py in interest_check_lambda folder
            code=lambda_.Code.from_asset("src/interest_check_function",
                bundling=BundlingOptions( # If it has dependencies like psycopg2
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c", (
                            "pip install -r requirements.txt -t /asset-output && "
                            "cp -au . /asset-output"
                        )
                    ]
                )
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[lambda_security_group],
            environment={
                "DB_HOST": db_cluster.cluster_endpoint.hostname,
                "DB_PORT": str(db_cluster.cluster_endpoint.port),
                "DB_NAME": db_name,
                "DB_CREDENTIALS_SECRET_ARN": db_credentials_secret.secret_arn,
                "APPLICATION_SECRETS_ARN": application_secrets_arn, # For WATI if needed
                "ENVIRONMENT_NAME": environment_name,
            },
            role=interest_check_lambda_role,
            timeout=Duration.minutes(5)
        )

        # Schedule to run daily (e.g., at 2 AM UTC)
        rule = events.Rule(self, "InterestCheckRule",
            schedule=events.Schedule.cron(minute="0", hour="2", day="*", month="*", year="*"),
            description="Periodically checks for users who showed interest but didn't complete booking."
        )
        rule.add_target(targets.LambdaFunction(interest_check_function))