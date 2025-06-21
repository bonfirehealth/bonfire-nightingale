from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    BundlingOptions,
    Duration
)
from constructs import Construct

class VoiceProxyEc2Stack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.Vpc,
                 voice_ec2_proxy_security_group: ec2.ISecurityGroup,
                 lambda_security_group: ec2.ISecurityGroup,
                 application_secrets_arn: str,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Tạo EC2 instance trong public subnet
        self.voice_proxy_instance = ec2.Instance(self, "VoiceProxyInstance",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.latest_amazon_linux2(),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=voice_ec2_proxy_security_group,
            key_pair=ec2.KeyPair.from_key_pair_name(self, "KeyPair", "nightingale-voice-proxy"),
            user_data=ec2.UserData.for_linux(),
            associate_public_ip_address=True,  # Enable public IP
        )
        
        # Allocate Elastic IP
        eip = ec2.CfnEIP(self, "VoiceProxyEIP")

        # Associate Elastic IP with EC2 instance
        ec2.CfnEIPAssociation(self, "VoiceProxyEIPAssociation",
            eip=eip.ref,
            instance_id=self.voice_proxy_instance.instance_id,
        )

        # Cài đặt PostgreSQL client
        self.voice_proxy_instance.user_data.add_commands(
            "yum update -y",
        )

        # Lambda Voice Call Executor
        # IAM Role không có gì thay đổi nhiều, vì nó vẫn cần các quyền tương tự
        # để truy cập VPC, secrets và ghi log.
        executor_lambda_role = iam.Role(self, "VoiceCallExecutorLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )

        common_lambda_env = {
            "APPLICATION_SECRETS_ARN": application_secrets_arn,
            "ENVIRONMENT_NAME": environment_name,
        }

        # Đây chính là Lambda sẽ được EventBridge Scheduler gọi
        self.voice_proxy_executor_function = lambda_.Function(self, "VoiceProxyExecutorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="app.lambda_handler",
            code=lambda_.Code.from_asset("src/voice_proxy_executor_function", bundling=BundlingOptions(
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