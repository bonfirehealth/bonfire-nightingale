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
            "OPENAI_API_KEY": "YOUR_OPENAI_KEY_HERE",
            "WATI_API_ENDPOINT": "YOUR_WATI_ENDPOINT_HERE",
            "WATI_ACCESS_TOKEN": "YOUR_WATI_TOKEN_HERE",
            "GOOGLE_EMAIL_ADDRESS": "YOUR_GMAIL_ADDRESS_HERE",
            "GOOGLE_APP_PASSWORD": "YOUR_GOOGLE_APP_PASSWORD_HERE",
            # Thêm các biến khác nếu cần
            # "EMAIL_DR_AMY": "dr.reale@example.com", # Ví dụ
            # "EMAIL_DR_JANE": "jane.pebble@example.com" # Ví dụ
        }

        self.application_secrets = secretsmanager.Secret(self, "ApplicationSecrets", # ID logic
            secret_name=f"{secret_prefix}/application_config", # Tên secret duy nhất
            description=f"Application configuration and secrets for Nightingale ({environment_name})",
            # Sử dụng generate_secret_string để tạo secret với cấu trúc JSON
            # Bạn sẽ cần cập nhật giá trị thực trong AWS Console sau khi deploy
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps(secret_json_template), # Chuyển dict thành JSON string
                generate_string_key="placeholder_for_initial_creation" # Key này không quan trọng, chỉ để CDK tạo secret
            ),
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY
        )
