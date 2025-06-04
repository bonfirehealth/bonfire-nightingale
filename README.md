# Nightingale Chatbot

## Prerequisites

- Python >= 3.11
- Docker
- NodeJS >= 22
- AWS CLI
- AWS CDK
- AWS Account
- WATI Account
- OpenAI Account
- Google Account

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure AWS CLI
aws configure

# Install AWS CDK
npm install -g aws-cdk

# Deploy the stack to dev environment
./deploy.sh

# Deploy the stack to prod environment
cdk deploy --context environment_name=prod
```
