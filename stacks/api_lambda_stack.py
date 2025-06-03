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
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        lambda_memory_ingest_val = lambda_memory_ingest
        lambda_memory_process_val = lambda_memory_process

        # IAM Role for Lambda functions
        lambda_base_role = iam.Role(self, "LambdaBaseRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )
        # Allow Lambda to read secrets
        db_credentials_secret.grant_read(lambda_base_role)
        application_secrets_object = secretsmanager.Secret.from_secret_complete_arn(self, "ImportedApplicationSecrets", application_secrets_arn)
        application_secrets_object.grant_read(lambda_base_role)

        # Environment variables for Lambda functions
        common_lambda_env = {
            "DB_HOST": db_cluster.cluster_endpoint.hostname,
            "DB_PORT": str(db_cluster.cluster_endpoint.port), # Convert port to string
            "DB_NAME": db_name,
            "DB_CREDENTIALS_SECRET_ARN": db_credentials_secret.secret_arn,
            "APPLICATION_SECRETS_ARN": application_secrets_arn,
            "MESSAGE_QUEUE_URL": message_queue.queue_url,
            "ENVIRONMENT_NAME": environment_name,
            # "EMAIL_DR_AMY": kwargs.get("email_dr_amy", ""), # Get from kwargs if passed in
            # "EMAIL_DR_JANE": kwargs.get("email_dr_jane", "")
        }

        # Lambda IngestFunction
        ingest_function_policy_statement = iam.PolicyStatement(
            actions=["sqs:SendMessage"],
            resources=[message_queue.queue_arn]
        )
        lambda_base_role.add_to_policy(ingest_function_policy_statement)

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
            role=lambda_base_role,
            timeout=Duration.seconds(60 if is_prod else 30),
            memory_size=lambda_memory_ingest_val,
            environment={
                **common_lambda_env,
                "MESSAGE_QUEUE_URL": message_queue.queue_url
            },
        )
        message_queue.grant_send_messages(ingest_function)

        # Lambda ProcessFunction
        process_function_policy_statement = iam.PolicyStatement(
            actions=["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
            resources=[message_queue.queue_arn]
        )
        lambda_base_role.add_to_policy(process_function_policy_statement)

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
            environment=common_lambda_env,
            role=lambda_base_role,
            timeout=Duration.minutes(5 if is_prod else 3), # OpenAI may take time
            memory_size=lambda_memory_process_val,
        )
        message_queue.grant_consume_messages(process_function) # Grant permission to consume messages from SQS

        # Add SQS event source to ProcessFunction
        process_function.add_event_source(
            lambda_event_sources.SqsEventSource(message_queue,
                batch_size=1,  # Xử lý 1 message mỗi lần invoke Lambda, phù hợp cho chatbot
                # max_batching_window=Duration.minutes(1), # Tùy chọn
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