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

# Bootstrap the stack
cdk bootstrap aws://305777245840/ap-southeast-1

# Deploy the stack to dev environment
./deploy.sh

# Deploy the stack to prod environment
cdk deploy --context environment_name=prod
```

## Initialize RDS
```bash
# Access EC2 Bastion instance -> Connect to RDS
# 1. Get your IP address from whatismyip.com
# 2. Add your IP address to the security group (Allow SSH from my IP) of the RDS instance
# 3. Connect to EC2 Bastion instance and move schema.sql to the instance:
ssh -i "<path_to_your_pem_file>" ec2-user@<BASTION_PUBLIC_DNS>
cp <local_path_to_schema.sql> ec2-user@<BASTION_PUBLIC_DNS>:~/
# 4. Connect to RDS:
# Go to Secrets Manager -> Secrets -> <RDS_SECRET_NAME> -> Retrieve secret value
# Copy the value of <RDS_SECRET_NAME> and paste it into the following command:
export PGPASSWORD=<RDS_PASSWORD>
psql -h <RDS_ENDPOINT> -U <RDS_USERNAME> -d <RDS_DATABASE>  # might need to install postgresql10
# 5. Initialize the database:
\i schema.sql;
```

## Appendix

### Install PostgreSQL client v10 on AWS Amazon Linux AMI
```bash
sudo amazon-linux-extras install postgresql10
```

## Create Stripe Product
1. Go to Stripe Dashboard -> Products -> Create Product
2. Go to Developers -> 