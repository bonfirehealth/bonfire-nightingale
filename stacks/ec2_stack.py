from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
)
from constructs import Construct

class BastionEc2Stack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.Vpc,
                 bastion_security_group: ec2.SecurityGroup,  # Nhận từ VPC Stack
                 rds_security_group: ec2.SecurityGroup,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Sử dụng Security Group đã được tạo trong VPC Stack
        self.bastion_sg = bastion_security_group

        # Tạo EC2 instance trong public subnet
        self.bastion_instance = ec2.Instance(self, "BastionInstance",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.latest_amazon_linux2(),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=self.bastion_sg,
            key_pair=ec2.KeyPair.from_key_pair_name(self, "KeyPair", "nightingale-bastion"),
            user_data=ec2.UserData.for_linux(),
        )
        
        # Cài đặt PostgreSQL client
        self.bastion_instance.user_data.add_commands(
            "yum update -y",
            "yum install postgresql -y"
        )