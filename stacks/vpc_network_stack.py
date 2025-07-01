from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    RemovalPolicy
)
from constructs import Construct

class VpcNetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 environment_name: str,
                 is_prod: bool,
                 nat_gateways_count: int,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC
        self.vpc = ec2.Vpc(self, "NightingaleVpc",
            max_azs=2, # Use 2 AZs for high availability
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="PublicSubnet",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="PrivateSubnetWithNat",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, # Change to PRIVATE_WITH_NAT if using CDK < 2.23.0
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="PrivateIsolatedSubnet", # For RDS
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24
                )
            ],
            nat_gateways=nat_gateways_count,
            # nat_gateway_provider=ec2.NatProvider.gateway() # If using CDK < 2.23.0
        )

        # Security Group cho Lambdas
        self.lambda_security_group = ec2.SecurityGroup(self, "LambdaSecurityGroup",
            vpc=self.vpc,
            description="Security group for Lambda functions",
            allow_all_outbound=True # Lambda needs to go out to call WATI, OpenAI, Google
        )

        # Security Group cho Bastion (tạo ở đây để tránh circular dependency)
        self.bastion_security_group = ec2.SecurityGroup(self, "BastionSecurityGroup",
            vpc=self.vpc,
            description="Security group for Bastion EC2 instance",
            allow_all_outbound=True
        )

        # Cho phép SSH vào Bastion từ VPC
        self.bastion_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4("10.0.0.0/16"),
            connection=ec2.Port.tcp(22),
            description="Allow SSH from VPC"
        )

        # Allow SSH from your specific IP (replace with your actual IP)
        your_ip = "1.55.14.60/32"
        self.bastion_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(your_ip),
            connection=ec2.Port.tcp(22),
            description="Allow SSH from my IP"
        )

        # Security Group cho Voice Proxy
        self.voice_ec2_proxy_security_group = ec2.SecurityGroup(self, "VoiceProxySecurityGroup",
            vpc=self.vpc,
            description="Security group for Voice Proxy EC2 instance",
            allow_all_outbound=True
        )

        # Cho phép SSH từ internet (public access)
        self.voice_ec2_proxy_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(22),
            description="Allow SSH from anywhere"
        )

        # Cho phép HTTPS cho WebSocket (port 443)
        self.voice_ec2_proxy_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS/WebSocket from anywhere"
        )

        # Security Group cho RDS
        self.rds_security_group = ec2.SecurityGroup(self, "RdsSecurityGroup",
            vpc=self.vpc,
            description="Security group for RDS Aurora cluster"
        )

        # Allow Lambda to connect to RDS
        self.rds_security_group.add_ingress_rule(
            peer=self.lambda_security_group,
            connection=ec2.Port.tcp(5432), # Port PostgreSQL
            description="Allow Lambda to connect to RDS"
        )

        # Allow Bastion to connect to RDS
        self.rds_security_group.add_ingress_rule(
            peer=self.bastion_security_group,
            connection=ec2.Port.tcp(5432),
            description="Allow Bastion EC2 to connect to RDS"
        )

        # Allow Voice Proxy to connect to RDS
        self.rds_security_group.add_ingress_rule(
            peer=self.voice_ec2_proxy_security_group,
            connection=ec2.Port.tcp(5432),
            description="Allow Voice Proxy EC2 to connect to RDS"
        )

        # (Optional) VPC Endpoints to enhance security and cost savings
        self.vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3) # Lambda needs to fetch code from S3
        self.vpc.add_interface_endpoint("SecretsManagerEndpoint", service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER)
        self.vpc.add_interface_endpoint("SQSEndpoint", service=ec2.InterfaceVpcEndpointAwsService.SQS)
        self.vpc.add_interface_endpoint("LogsEndpoint", service=ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS)
        # self.vpc.add_interface_endpoint("RDSEndpoint", service=ec2.InterfaceVpcEndpointAwsService.RDS_DATA) # If using RDS Data API