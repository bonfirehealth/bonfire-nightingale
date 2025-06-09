from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_rds as rds,
    RemovalPolicy,
    Duration
)
from constructs import Construct

class DatabaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 vpc: ec2.IVpc,
                 rds_security_group: ec2.ISecurityGroup,
                 rds_username: str,
                 db_name: str,
                 environment_name: str,
                 is_prod: bool,
                 # rds_instance_size: ec2.InstanceSize, # Nhận instance size
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        rds_instance_size_str = self.node.try_get_context(f"{environment_name}:rds_instance_size") or \
                                ("R6G_LARGE" if is_prod else "BURSTABLE3_MEDIUM") # Mặc định nếu không có trong context
        
        # Convert string to ec2.InstanceType
        if "BURSTABLE3" in rds_instance_size_str:
            instance_class = ec2.InstanceClass.BURSTABLE3
            instance_size_enum = getattr(ec2.InstanceSize, rds_instance_size_str.split('_')[1])
        elif "R6G" in rds_instance_size_str: # Example for Graviton
            instance_class = ec2.InstanceClass.R6G
            instance_size_enum = getattr(ec2.InstanceSize, rds_instance_size_str.split('_')[1])
        else: # Default
            instance_class = ec2.InstanceClass.BURSTABLE3
            instance_size_enum = ec2.InstanceSize.MEDIUM

        actual_rds_instance_type = ec2.InstanceType.of(instance_class, instance_size_enum)

        # Secret for RDS Credentials
        self.db_credentials_secret = rds.DatabaseSecret(self, "DBCredentialsSecret",
            username=rds_username
        )

        self.db_cluster = rds.DatabaseCluster(self, "DatabaseCluster", # ID logic
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_6
            ),
            credentials=rds.Credentials.from_secret(self.db_credentials_secret),
            writer=rds.ClusterInstance.provisioned("WriterInstance",
                instance_type=actual_rds_instance_type,
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[rds_security_group],
            default_database_name=db_name,
            backup=rds.BackupProps(
                retention=Duration.days(30 if is_prod else 7)
            ),
            removal_policy=RemovalPolicy.SNAPSHOT if is_prod else RemovalPolicy.DESTROY,
        )