from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
)
from constructs import Construct

class VoiceProxyEc2Stack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.Vpc,
                 voice_proxy_security_group: ec2.SecurityGroup,  # Nhận từ VPC Stack
                 rds_security_group: ec2.SecurityGroup,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Sử dụng Security Group đã được tạo trong VPC Stack
        self.voice_proxy_sg = voice_proxy_security_group

        # Tạo EC2 instance trong public subnet
        self.voice_proxy_instance = ec2.Instance(self, "VoiceProxyInstance",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.latest_amazon_linux2(),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=self.voice_proxy_sg,
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