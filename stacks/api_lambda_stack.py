from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_apigatewayv2 as apigwv2, # HTTP API
    aws_apigatewayv2_integrations as apigwv2_integrations, # HTTP API Integrations
    aws_sqs as sqs,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    aws_iam as iam,
    aws_lambda_event_sources as lambda_event_sources,
    aws_scheduler as scheduler,  # Add this import for EventBridge Scheduler
    Duration,
    BundlingOptions,
    RemovalPolicy,
    CfnOutput
)
from constructs import Construct

class ApiLambdaStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.IVpc,
                 lambda_security_group: ec2.ISecurityGroup,
                 message_queue: sqs.IQueue,
                 db_cluster: rds.IDatabaseCluster,
                 db_credentials_secret: secretsmanager.ISecret,
                 application_secrets_arn: str,
                 db_name: str,
                 environment_name: str,
                 is_prod: bool,
                 lambda_memory_ingest: int,
                 lambda_memory_process: int,
                 nudge_executor_function_arn: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        lambda_memory_ingest_val = lambda_memory_ingest
        lambda_memory_process_val = lambda_memory_process

        ingest_lambda_role = iam.Role(self, "IngestLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )
        db_credentials_secret.grant_read(ingest_lambda_role)
        application_secrets_object = secretsmanager.Secret.from_secret_complete_arn(self, "ImportedApplicationSecrets", application_secrets_arn)
        application_secrets_object.grant_read(ingest_lambda_role)
        message_queue.grant_send_messages(ingest_lambda_role)

        # Role cho ProcessFunction
        process_lambda_role = iam.Role(self, "ProcessLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )
        db_credentials_secret.grant_read(process_lambda_role)
        application_secrets_object.grant_read(process_lambda_role)
        message_queue.grant_consume_messages(process_lambda_role)

        # 1. Tạo IAM Role mà EventBridge Scheduler sẽ sử dụng để gọi Lambda Executor.
        scheduler_role = iam.Role(self, "EventBridgeSchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            description="IAM Role for EventBridge Scheduler to invoke Nudge Executor Lambda"
        )
        # Cấp quyền cho Role này để gọi Lambda Executor (nudge_executor_function)
        scheduler_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["lambda:InvokeFunction"],
            resources=[nudge_executor_function_arn]
        ))

        # 2. Tạo một Schedule Group để quản lý tất cả các schedule của trial.
        # FIXED: Use EventBridge Scheduler's CfnScheduleGroup instead of iam.CfnGroup
        schedule_group = scheduler.CfnScheduleGroup(self, "NightingaleTrialScheduleGroup",
            name=f"nightingale-trial-schedules-{environment_name}"
        )

        # 3. Cho phép ProcessFunction tạo/xóa schedule TRONG group đã tạo ở trên.
        process_lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "scheduler:CreateSchedule",
                "scheduler:DeleteSchedule",
                "scheduler:UpdateSchedule",
                "scheduler:GetSchedule"
            ],
            resources=[
                f"arn:aws:scheduler:{self.region}:{self.account}:schedule/{schedule_group.name}/*"
            ]
        ))
        
        # 4. Cấp quyền iam:PassRole. Rất quan trọng!
        # Lambda cần quyền này để "giao" `scheduler_role` cho dịch vụ EventBridge.
        process_lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["iam:PassRole"],
            resources=[scheduler_role.role_arn]
        ))

        # Environment variables for Lambda functions
        common_lambda_env = {
            "DB_HOST": db_cluster.cluster_endpoint.hostname,
            "DB_PORT": str(db_cluster.cluster_endpoint.port), # Convert port to string
            "DB_NAME": db_name,
            "DB_CREDENTIALS_SECRET_ARN": db_credentials_secret.secret_arn,
            "APPLICATION_SECRETS_ARN": application_secrets_arn,
            "MESSAGE_QUEUE_URL": message_queue.queue_url,
            "ENVIRONMENT_NAME": environment_name,
        }

        # Ingest Function
        ingest_function = lambda_.Function(self, "IngestFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="app.lambda_handler",
            code=lambda_.Code.from_asset(
                "src/ingest_function",
                bundling=BundlingOptions(
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
            role=ingest_lambda_role,
            timeout=Duration.seconds(60 if is_prod else 30),
            memory_size=lambda_memory_ingest_val,
            environment={
                **common_lambda_env,
                "MESSAGE_QUEUE_URL": message_queue.queue_url
            },
        )

        # Process Function
        process_function = lambda_.Function(self, "ProcessFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="app.lambda_handler",
            code=lambda_.Code.from_asset("src/process_function", bundling=BundlingOptions(
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
            environment={
                **common_lambda_env,
                "MESSAGE_QUEUE_URL": message_queue.queue_url,
                "NUDGE_EXECUTOR_LAMBDA_ARN": nudge_executor_function_arn,
                "EVENTBRIDGE_SCHEDULER_ROLE_ARN": scheduler_role.role_arn,
                "SCHEDULE_GROUP_NAME": schedule_group.name  # Use .name instead of .group_name
            },
            role=process_lambda_role,
            timeout=Duration.minutes(5 if is_prod else 3), # OpenAI may take time
            memory_size=lambda_memory_process_val,
        )
        message_queue.grant_consume_messages(process_function) # Grant permission to consume messages from SQS

        # Add SQS event source to ProcessFunction
        process_function.add_event_source(
            lambda_event_sources.SqsEventSource(message_queue,
                batch_size=1,  # Xử lý 1 message mỗi lần invoke Lambda, phù hợp cho chatbot
                report_batch_item_failures=True # Quan trọng để xử lý lỗi từng phần trong batch
            )
        )

        # API Gateway (HTTP API)
        http_api = apigwv2.HttpApi(self, "NightingaleHttpApi",
            description=f"HTTP API for Nightingale Webhook for {environment_name}",
            cors_preflight=apigwv2.CorsPreflightOptions( # Configure CORS if needed
                allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key"],
                allow_methods=[apigwv2.CorsHttpMethod.POST, apigwv2.CorsHttpMethod.OPTIONS],
                allow_origins=["*"], # Or specify WATI domain
                max_age=Duration.days(1)
            )
        )

        # Integration between API Gateway and IngestFunction
        ingest_integration = apigwv2_integrations.HttpLambdaIntegration("IngestIntegration", ingest_function)

        http_api.add_routes(
            path="/webhook/wati", # Endpoint for WATI webhook
            methods=[apigwv2.HttpMethod.POST],
            integration=ingest_integration
        )

        CfnOutput(self, "ApiGatewayUrl", value=http_api.url)