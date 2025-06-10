import os
import aws_cdk as cdk

from stacks.vpc_network_stack import VpcNetworkStack
from stacks.secrets_stack import SecretsStack
from stacks.database_stack import DatabaseStack
from stacks.dynamodb_stack import DynamoDBStack
from stacks.messaging_stack import MessagingStack
from stacks.api_lambda_stack import ApiLambdaStack
from stacks.nudge_executor_stack import NudgeExecutorStack
from stacks.ec2_stack import BastionEc2Stack

app = cdk.App()

# Get values from context (e.g., from cdk.json or command line -c)
environment_name = app.node.try_get_context("environment_name")
if not environment_name:
    raise ValueError("Context variable 'environment_name' (e.g., 'dev', 'prod') is required.")

is_prod = environment_name == "prod"

rds_username = app.node.try_get_context("rds_username")
db_name_prefix = app.node.try_get_context("db_name_prefix")
db_name = f"{db_name_prefix}_{environment_name}"

lambda_memory_ingest = app.node.try_get_context(f"{environment_name}:lambda_memory_ingest") or 256
lambda_memory_process = app.node.try_get_context(f"{environment_name}:lambda_memory_process") or 512
lambda_memory_scheduled = app.node.try_get_context(f"{environment_name}:lambda_memory_scheduled") or 256
nat_gateways_count = app.node.try_get_context(f"{environment_name}:nat_gateways") or 1

stack_props = {
    "env": cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region=os.getenv('CDK_DEFAULT_REGION')),
    "environment_name": environment_name,
    "is_prod": is_prod
}


# Stack for VPC and Networking
vpc_stack = VpcNetworkStack(app, f"NightingaleVpcStack-{environment_name}",
    **stack_props,
    nat_gateways_count=nat_gateways_count
)

# Stack for Bastion EC2 (sử dụng Security Group từ VPC Stack)
bastion_stack = BastionEc2Stack(app, f"NightingaleBastionStack-{environment_name}",
    vpc=vpc_stack.vpc,
    bastion_security_group=vpc_stack.bastion_security_group,  # Truyền Bastion SG từ VPC Stack
    rds_security_group=vpc_stack.rds_security_group,
    **stack_props
)
bastion_stack.add_dependency(vpc_stack)

# Stack for Secrets Manager
secrets_stack = SecretsStack(app, f"NightingaleSecretsStack-{environment_name}",
    **stack_props
)

# Stack for RDS Database
db_stack = DatabaseStack(app, f"NightingaleDatabaseStack-{environment_name}",
    vpc=vpc_stack.vpc,
    rds_security_group=vpc_stack.rds_security_group,
    rds_username=rds_username,
    db_name=db_name,
    # rds_instance_size=rds_instance_size, # Truyền vào instance size
    **stack_props
)
db_stack.add_dependency(vpc_stack)
db_stack.add_dependency(secrets_stack) # RDS credentials will be stored in Secrets Manager

# Stack for SQS Messaging
messaging_stack = MessagingStack(app, f"NightingaleMessagingStack-{environment_name}",
    **stack_props
)

# Stack for DynamoDB
dynamodb_stack = DynamoDBStack(app, f"NightingaleDynamoDBStack-{environment_name}",
    **stack_props
)

# Stack for Nudge Executor Function
nudge_executor_stack = NudgeExecutorStack(app, f"NightingaleNudgeExecutorStack-{environment_name}",
    vpc=vpc_stack.vpc,
    lambda_security_group=vpc_stack.lambda_security_group,
    db_cluster=db_stack.db_cluster,
    db_credentials_secret=db_stack.db_credentials_secret,
    db_name=db_name,
    application_secrets_arn=secrets_stack.application_secrets.secret_arn,
    lambda_memory_scheduled=lambda_memory_scheduled,
    **stack_props
)
nudge_executor_stack.add_dependency(vpc_stack)
nudge_executor_stack.add_dependency(db_stack)
nudge_executor_stack.add_dependency(secrets_stack)


# Stack for API Gateway and Lambda functions
api_lambda_stack = ApiLambdaStack(app, f"NightingaleApiLambdaStack-{environment_name}",
    vpc=vpc_stack.vpc,
    lambda_security_group=vpc_stack.lambda_security_group,
    message_queue=messaging_stack.message_queue,
    active_users_table=dynamodb_stack.active_users_table,
    metrics_table=dynamodb_stack.metrics_table,
    db_cluster=db_stack.db_cluster,
    db_credentials_secret=db_stack.db_credentials_secret,
    db_name=db_name,
    application_secrets_arn=secrets_stack.application_secrets.secret_arn,
    lambda_memory_ingest=lambda_memory_ingest,
    lambda_memory_process=lambda_memory_process,
    nudge_executor_function_arn=nudge_executor_stack.nudge_executor_function.function_arn,
    **stack_props
)
api_lambda_stack.add_dependency(vpc_stack)
api_lambda_stack.add_dependency(db_stack)
api_lambda_stack.add_dependency(messaging_stack)
api_lambda_stack.add_dependency(dynamodb_stack)
api_lambda_stack.add_dependency(secrets_stack)
api_lambda_stack.add_dependency(nudge_executor_stack)

app.synth()