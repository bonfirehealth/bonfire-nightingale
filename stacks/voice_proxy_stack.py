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
                 lambda_security_group: ec2.ISecurityGroup,  # Vẫn cần cho Lambda
                 application_secrets_arn: str,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Sử dụng Default VPC
        default_vpc = ec2.Vpc.from_lookup(self, "DefaultVPC", is_default=True)
        
        # Tạo Security Group riêng cho EC2 trong Default VPC
        voice_ec2_security_group = ec2.SecurityGroup(self, "VoiceProxySecurityGroup",
            vpc=default_vpc,
            description="Security group for Voice Proxy EC2",
            allow_all_outbound=True  # Allow all outbound traffic
        )
        
        # Thêm inbound rules
        voice_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(22),
            description="Allow SSH from anywhere"
        )
        
        voice_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
            description="Allow HTTP from anywhere"
        )
        
        voice_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS from anywhere"
        )
        
        # Thêm port tùy chỉnh nếu cần (ví dụ cho voice proxy)
        voice_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(8080),
            description="Allow custom port 8080"
        )
        
        # Tạo IAM role cho EC2 (optional nhưng recommended)
        ec2_role = iam.Role(self, "VoiceProxyInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
                # Thêm permissions khác nếu cần
            ]
        )
        
        # Tạo EC2 instance trong Default VPC
        self.voice_proxy_instance = ec2.Instance(self, "VoiceProxyInstance",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.latest_amazon_linux2(),
            vpc=default_vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),  # Phải chỉ định rõ
            security_group=voice_ec2_security_group,
            key_pair=ec2.KeyPair.from_key_pair_name(self, "KeyPair", "nightingale-voice-proxy"),
            user_data=ec2.UserData.for_linux(),
            associate_public_ip_address=True,
            role=ec2_role,
        )
        
        # Allocate Elastic IP (optional - nếu muốn IP cố định)
        eip = ec2.CfnEIP(self, "VoiceProxyEIP")
        
        # Associate Elastic IP with EC2 instance
        ec2.CfnEIPAssociation(self, "VoiceProxyEIPAssociation",
            eip=eip.ref,
            instance_id=self.voice_proxy_instance.instance_id,
        )
        
        # # User data setup
        # self.voice_proxy_instance.user_data.add_commands(
        #     "yum update -y",
        #     "yum install -y docker",
        #     "systemctl start docker",
        #     "systemctl enable docker",
        #     "usermod -a -G docker ec2-user",
        #     # Thêm các commands khác nếu cần
        # )
        
        # Lambda function vẫn có thể dùng VPC riêng hoặc không dùng VPC
        # Nếu Lambda không cần kết nối tới EC2 trực tiếp, có thể bỏ VPC
        
        executor_lambda_role = iam.Role(self, "VoiceCallExecutorLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                # Bỏ VPC access nếu không cần
            ]
        )
        
        common_lambda_env = {
            "APPLICATION_SECRETS_ARN": application_secrets_arn,
            "ENVIRONMENT_NAME": environment_name,
            "EC2_INSTANCE_ID": self.voice_proxy_instance.instance_id,
            "EC2_PUBLIC_IP": eip.ref,  # Có thể truyền IP để Lambda biết
        }
        
        # Lambda không cần VPC nếu chỉ call EC2 qua public IP
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
            environment=common_lambda_env,
            role=executor_lambda_role,
            timeout=Duration.seconds(30),
            memory_size=256  # Sửa biến lambda_memory_scheduled
        )