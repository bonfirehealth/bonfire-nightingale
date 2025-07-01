from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    BundlingOptions,
    Duration
)
from constructs import Construct

class VoiceProxyEc2Stack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.IVpc,
                 lambda_security_group: ec2.ISecurityGroup,
                 voice_ec2_proxy_security_group: ec2.ISecurityGroup,
                 db_cluster: rds.IDatabaseCluster,
                 db_credentials_secret: secretsmanager.ISecret,
                 application_secrets_arn: str,
                 db_name: str,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Tạo IAM role cho EC2
        ec2_role = iam.Role(self, "VoiceProxyInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ]
        )
        
        # Grant EC2 access to secrets
        application_secrets_object = secretsmanager.Secret.from_secret_complete_arn(
            self, "ImportedApplicationSecrets", application_secrets_arn)
        application_secrets_object.grant_read(ec2_role)
        db_credentials_secret.grant_read(ec2_role)
        
        # Tạo EC2 instance trong custom VPC, public subnet
        self.voice_proxy_instance = ec2.Instance(self, "VoiceProxyInstance",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.latest_amazon_linux2(),
            vpc=vpc,  # Sử dụng custom VPC
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),  # Public subnet để có internet access
            security_group=voice_ec2_proxy_security_group,  # Sử dụng security group đã được cấu hình
            key_pair=ec2.KeyPair.from_key_pair_name(self, "KeyPair", "nightingale-voice-proxy"),
            user_data=ec2.UserData.for_linux(),
            associate_public_ip_address=True,  # Quan trọng: cần public IP
            role=ec2_role,
        )
        
        # Allocate Elastic IP để có IP cố định
        eip = ec2.CfnEIP(self, "VoiceProxyEIP")
        
        # Associate Elastic IP with EC2 instance
        ec2.CfnEIPAssociation(self, "VoiceProxyEIPAssociation",
            eip=eip.ref,
            instance_id=self.voice_proxy_instance.instance_id,
        )
        
        # User data để setup cơ bản
        self.voice_proxy_instance.user_data.add_commands(
            "yum update -y",
            "yum install -y docker postgresql15",  # Cài PostgreSQL client để test connection
            "systemctl start docker",
            "systemctl enable docker",
            "usermod -a -G docker ec2-user",
            # Cài AWS CLI nếu chưa có
            "yum install -y aws-cli",
        )
        
        # Lambda function executor
        executor_lambda_role = iam.Role(self, "VoiceCallExecutorLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )
        
        # Grant Lambda access to secrets and database
        application_secrets_object.grant_read(executor_lambda_role)
        db_credentials_secret.grant_read(executor_lambda_role)
        
        common_lambda_env = {
            "APPLICATION_SECRETS_ARN": application_secrets_arn,
            "ENVIRONMENT_NAME": environment_name,
            "EC2_INSTANCE_ID": self.voice_proxy_instance.instance_id,
            "EC2_PUBLIC_IP": eip.ref,
            "DB_HOST": db_cluster.cluster_endpoint.hostname,
            "DB_PORT": str(db_cluster.cluster_endpoint.port),
            "DB_NAME": db_name,
            "DB_CREDENTIALS_SECRET_ARN": db_credentials_secret.secret_arn,
        }
        
        # Lambda function có thể cần VPC nếu phải truy cập database
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
            timeout=Duration.seconds(30),
            memory_size=256
        )