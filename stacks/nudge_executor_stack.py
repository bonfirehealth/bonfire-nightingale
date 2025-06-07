from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    aws_iam as iam,
    BundlingOptions,
    Duration
)
from constructs import Construct

# Đổi tên class cho rõ ràng
class NudgeExecutorStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.IVpc,
                 lambda_security_group: ec2.ISecurityGroup,
                 db_cluster: rds.IDatabaseCluster,
                 db_credentials_secret: secretsmanager.ISecret,
                 application_secrets_arn: str,
                 db_name: str,
                 environment_name: str,
                 is_prod: bool,
                 lambda_memory_scheduled: int, # Bạn có thể đổi tên biến này thành lambda_memory_executor
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # IAM Role không có gì thay đổi nhiều, vì nó vẫn cần các quyền tương tự
        # để truy cập VPC, secrets và ghi log.
        executor_lambda_role = iam.Role(self, "NudgeExecutorLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )

        db_credentials_secret.grant_read(executor_lambda_role)
        application_secrets_object = secretsmanager.Secret.from_secret_complete_arn(self, "ImportedApplicationSecrets", application_secrets_arn)
        application_secrets_object.grant_read(executor_lambda_role)
        
        # Thêm quyền gửi tin nhắn WhatsApp (ví dụ nếu dùng SNS hoặc SES)
        # executor_lambda_role.add_to_policy(iam.PolicyStatement(...))

        common_lambda_env = {
            "DB_HOST": db_cluster.cluster_endpoint.hostname,
            "DB_PORT": str(db_cluster.cluster_endpoint.port),
            "DB_NAME": db_name,
            "DB_CREDENTIALS_SECRET_ARN": db_credentials_secret.secret_arn,
            "APPLICATION_SECRETS_ARN": application_secrets_arn,
            # Thêm các biến môi trường cần thiết để gửi tin nhắn
        }

        # Đây chính là Lambda sẽ được EventBridge Scheduler gọi
        self.nudge_executor_function = lambda_.Function(self, "NudgeExecutorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="app.lambda_handler",
            code=lambda_.Code.from_asset("src/nudge_executor_function", bundling=BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                command=[
                    "bash", "-c",
                    "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output"
                ]
            )),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[lambda_security_group],
            environment=common_lambda_env,
            role=executor_lambda_role,
            timeout=Duration.seconds(30), # Có thể giảm timeout vì task này rất nhanh
            memory_size=lambda_memory_scheduled
        )