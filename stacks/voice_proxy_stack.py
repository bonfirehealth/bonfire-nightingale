from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecr_assets as ecr_assets,
    aws_iam as iam,
    aws_logs as logs,
    aws_scheduler as scheduler,
    aws_secretsmanager as secretsmanager,
    aws_ssm as ssm,
)
from constructs import Construct

class VoiceProxyStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.IVpc,
                 db_credentials_secret: secretsmanager.ISecret,
                 application_secrets_arn: str,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. Create ECS Cluster
        cluster = ecs.Cluster(self, "VoiceProxyCluster", vpc=vpc)

        # 2. Build and push Docker image to ECR
        # CDK will automatically build image from the directory you specify and push to ECR
        image_asset = ecr_assets.DockerImageAsset(self, "VoiceProxyImageAsset",
            directory="src/voice_call_proxy",
        )

        # 3. Create Log Group for Fargate task
        log_group = logs.LogGroup(self, "FargateLogGroup",
            log_group_name=f"/ecs/{construct_id}",
            retention=logs.RetentionDays.ONE_MONTH
        )

        # 4. Create Task Definition for Fargate
        task_definition = ecs.FargateTaskDefinition(self, "VoiceProxyTaskDef",
            memory_limit_mib=1024, # 1 GB
            cpu=512 # 0.5 vCPU
        )
        task_definition.add_container("VoiceProxyContainer",
            image=ecs.ContainerImage.from_docker_image_asset(image_asset),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="voice-proxy",
                log_group=log_group
            ),
            port_mappings=[ecs.PortMapping(container_port=8080)],
            # Truyền các secret vào container nếu cần
            # secrets={ "ELEVENLABS_API_KEY": ecs.Secret.from_secrets_manager(...) }
        )

        # Add policy to task role to allow DescribeNetworkInterfaces
        task_definition.task_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["ec2:DescribeNetworkInterfaces"],
            resources=["*"]
        ))

        # 5. Create IAM Role for EventBridge Scheduler to run Fargate task (giữ nguyên)
        scheduler_role = iam.Role(self, "SchedulerToFargateRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com")
        )
        task_definition.grant_run(scheduler_role)
        if task_definition.execution_role:
            task_definition.execution_role.grant_pass_role(scheduler_role)

        # 6. Create a Schedule Group to manage voice call schedules (giữ nguyên)
        schedule_group = scheduler.CfnScheduleGroup(self, "VoiceCallScheduleGroup",
            name=f"nightingale-voice-calls-{environment_name}"
        )

        self.scheduler_to_fargate_role = scheduler_role
        self.voice_call_schedule_group = schedule_group

        param_prefix = f"/nightingale/{environment_name}/voice-proxy"

        # Important: Store các giá trị hay thay đổi vào SSM Parameter Store để tránh xung đột
        ssm.StringParameter(self, "ClusterArnParam",
            parameter_name=f"{param_prefix}/cluster-arn",
            string_value=cluster.cluster_arn
        )
        ssm.StringParameter(self, "TaskDefArnParam",
            parameter_name=f"{param_prefix}/task-def-arn",
            string_value=task_definition.task_definition_arn
        )
        ssm.StringParameter(self, "SubnetIdParam",
            parameter_name=f"{param_prefix}/subnet-id",
            string_value=vpc.public_subnets[0].subnet_id
        )
