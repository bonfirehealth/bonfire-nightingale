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
    aws_scheduler as scheduler,
    Duration,
    BundlingOptions,
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
                 voice_proxy_executor_function_arn: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        lambda_memory_ingest_val = lambda_memory_ingest
        lambda_memory_process_val = lambda_memory_process

        # --------------------------------------------
        # ROLES
        # --------------------------------------------
        # Role for IngestFunction
        # This role allows the Lambda to access RDS, Secrets Manager, and SQS
        ingest_lambda_role = iam.Role(self, "IngestLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )
        application_secrets_object = secretsmanager.Secret.from_secret_complete_arn(self, "ImportedApplicationSecrets", application_secrets_arn)
        application_secrets_object.grant_read(ingest_lambda_role)
        message_queue.grant_send_messages(ingest_lambda_role)

        # Role for ProcessFunction
        # This role allows the Lambda to access RDS, Secrets Manager, SQS, and EventBridge Scheduler
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

        # Role for Stripe Webhook Lambda
        # This role allows the Lambda to access RDS and Secrets Manager
        stripe_lambda_role = iam.Role(self, "StripeWebhookLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )
        db_credentials_secret.grant_read(stripe_lambda_role)
        application_secrets_object.grant_read(stripe_lambda_role)

        # Role for Dashboard Lambda
        # This role allows the Lambda to access RDS and Secrets Manager
        dashboard_lambda_role = iam.Role(self, "DashboardLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole") # Cần để chạy trong VPC
            ]
        )
        db_credentials_secret.grant_read(dashboard_lambda_role)
        application_secrets_object.grant_read(dashboard_lambda_role)

        # 1. Create IAM Role for EventBridge Scheduler to invoke Nudge Executor Lambda
        scheduler_role = iam.Role(self, "EventBridgeSchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            description="IAM Role for EventBridge Scheduler to invoke Nudge Executor Lambda"
        )
        # Grant permission to invoke Nudge Executor Lambda
        scheduler_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["lambda:InvokeFunction"],
            resources=[nudge_executor_function_arn]
        ))

        # Create IAM Role for EventBridge Scheduler to invoke Voice Proxy Lambda
        voice_scheduler_role = iam.Role(self, "VoiceSchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            description="IAM Role for EventBridge Scheduler to invoke Voice Proxy Lambda"
        )
        # Grant permission to invoke Voice Proxy Lambda
        voice_scheduler_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["lambda:InvokeFunction"],
            resources=[voice_proxy_executor_function_arn]
        ))

        # 2. Create a Schedule Group to manage all schedules for trial
        schedule_group = scheduler.CfnScheduleGroup(self, "NightingaleTrialScheduleGroup",
            name=f"nightingale-trial-schedules-{environment_name}"
        )

        voice_schedule_group = scheduler.CfnScheduleGroup(self, "NightingaleVoiceScheduleGroup",
            name=f"nightingale-voice-schedules-{environment_name}"
        )

        # 3. Grant ProcessFunction permission to create/delete schedules in the group created above
        process_lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "scheduler:CreateSchedule", "scheduler:DeleteSchedule",
                "scheduler:UpdateSchedule", "scheduler:GetSchedule"
            ],
            resources=[
                f"arn:aws:scheduler:{self.region}:{self.account}:schedule/{schedule_group.name}/*",
                f"arn:aws:scheduler:{self.region}:{self.account}:schedule/{voice_schedule_group.name}/*",
            ]
        ))
        
        # 4. Grant iam:PassRole permission. Very important!
        # Lambda needs this permission to "pass" `scheduler_role` to EventBridge service.
        process_lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["iam:PassRole"],
            resources=[
                scheduler_role.role_arn,
                voice_scheduler_role.role_arn
            ]
        ))

        # --------------------------------------------
        # ENVIRONMENT VARIABLES
        # --------------------------------------------
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

        # --------------------------------------------
        # LAMBDA FUNCTIONS
        # --------------------------------------------
        # Ingest Function
        # This function will receive webhooks from WATI and send messages to SQS
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
                "MESSAGE_QUEUE_URL": message_queue.queue_url,
            },
        )

        # Process Function
        # This function will process messages from SQS and perform corresponding actions
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
                "SCHEDULE_GROUP_NAME": schedule_group.name,
                "VOICE_PROXY_EXECUTOR_LAMBDA_ARN": voice_proxy_executor_function_arn,
                "EVENTBRIDGE_VOICE_SCHEDULER_ROLE_ARN": voice_scheduler_role.role_arn,
                "VOICE_SCHEDULE_GROUP_NAME": voice_schedule_group.name,
            },
            role=process_lambda_role,
            timeout=Duration.minutes(5 if is_prod else 3), # OpenAI may take time
            memory_size=lambda_memory_process_val,
        )
        message_queue.grant_consume_messages(process_function) # Grant permission to consume messages from SQS

        # Add SQS event source to ProcessFunction
        process_function.add_event_source(
            lambda_event_sources.SqsEventSource(message_queue,
                batch_size=1,  # Process 1 message per Lambda invocation, suitable for chatbot
                report_batch_item_failures=True # Important to handle errors in batch
            )
        )

        # Dashboard Function
        # This function will query the RDS database and return active users
        dashboard_function = lambda_.Function(self, "DashboardFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="app.lambda_handler",
            code=lambda_.Code.from_asset(
                "src/dashboard_function",
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
            role=dashboard_lambda_role,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment=common_lambda_env,
        )

        # Stripe Webhook Function
        # This function will handle Stripe webhooks
        stripe_webhook_function = lambda_.Function(self, "StripeWebhookFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="app.lambda_handler",
            code=lambda_.Code.from_asset(
                "src/stripe_webhook_function",
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
            role=stripe_lambda_role,
            timeout=Duration.seconds(60),
            memory_size=256,
            environment=common_lambda_env,
        )

        # ---------------------------------------------
        # API Gateway (HTTP API)
        # ---------------------------------------------
        http_api = apigwv2.HttpApi(self, "NightingaleHttpApi",
            description=f"HTTP API for Nightingale Webhook for {environment_name}",
            cors_preflight=apigwv2.CorsPreflightOptions( # Configure CORS if needed
                allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "Stripe-Signature"],
                allow_methods=[apigwv2.CorsHttpMethod.POST, apigwv2.CorsHttpMethod.OPTIONS],
                allow_origins=["*"], # Or specify domains
                max_age=Duration.days(1)
            )
        )

        # Integration between API Gateway and IngestFunction
        ingest_integration = apigwv2_integrations.HttpLambdaIntegration("IngestIntegration", ingest_function)

        # Integration between API Gateway and Stripe Webhook Function
        stripe_integration = apigwv2_integrations.HttpLambdaIntegration("StripeIntegration", stripe_webhook_function)

        # Integration between API Gateway and Dashboard Function
        dashboard_integration = apigwv2_integrations.HttpLambdaIntegration(
            "DashboardIntegration",
            dashboard_function
        )

        http_api.add_routes(
            path="/webhook/wati", # Endpoint for WATI webhook
            methods=[apigwv2.HttpMethod.POST],
            integration=ingest_integration
        )

        # Add Stripe webhook endpoint
        http_api.add_routes(
            path="/webhook/stripe", # Endpoint for Stripe webhook
            methods=[apigwv2.HttpMethod.POST],
            integration=stripe_integration
        )

        # Add Stripe success endpoint
        http_api.add_routes(
            path="/stripe/success", # Endpoint for Stripe success
            methods=[apigwv2.HttpMethod.GET],
            integration=stripe_integration
        )

        # Add Stripe cancel endpoint
        http_api.add_routes(
            path="/stripe/cancel", # Endpoint for Stripe cancel
            methods=[apigwv2.HttpMethod.GET],
            integration=stripe_integration
        )

        # Add Dashboard endpoint
        http_api.add_routes(
            path="/dashboard", # Endpoint để xem dashboard
            methods=[apigwv2.HttpMethod.GET],
            integration=dashboard_integration
        )

        CfnOutput(self, "ApiGatewayUrl", value=http_api.url)
        CfnOutput(self, "StripeWebhookUrl", value=f"{http_api.url}webhook/stripe")
        CfnOutput(self, "DashboardUrl", value=f"{http_api.url}dashboard", description="URL to view the active users dashboard")