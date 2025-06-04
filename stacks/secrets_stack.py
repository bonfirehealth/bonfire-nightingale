import os
from aws_cdk import (
    Stack,
    aws_secretsmanager as secretsmanager,
    RemovalPolicy
)
from constructs import Construct
import json

class SecretsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 environment_name: str,
                 is_prod: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        secret_prefix = f"nightingale/{environment_name}"

        secret_json_template = {
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
            "WATI_API_ENDPOINT": os.getenv("WATI_API_ENDPOINT"),
            "WATI_ACCESS_TOKEN": os.getenv("WATI_ACCESS_TOKEN"),
            "GOOGLE_EMAIL_ADDRESS": os.getenv("GOOGLE_EMAIL_ADDRESS"),
            "GOOGLE_APP_PASSWORD": os.getenv("GOOGLE_APP_PASSWORD"),
            # "EMAIL_DR_AMY": "dr.reale@example.com",
            # "EMAIL_DR_JANE": "jane.pebble@example.com"
        }

        self.application_secrets = secretsmanager.Secret(self, "ApplicationSecrets", # ID logic
            secret_name=f"{secret_prefix}/application_config", # Tên secret duy nhất
            description=f"Application configuration and secrets for Nightingale ({environment_name})",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps(secret_json_template), # Chuyển dict thành JSON string
                generate_string_key="placeholder_for_initial_creation" # Key này không quan trọng, chỉ để CDK tạo secret
            ),
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY
        )
