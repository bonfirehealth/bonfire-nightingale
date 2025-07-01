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

### Install docker on Amazon Linux AMI
```bash
sudo yum update -y
sudo amazon-linux-extras install docker
sudo service docker start
sudo usermod -a -G docker ec2-user
```

### Install ngrok
```bash
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz -P /tmp
curl -o /tmp/ngrok-v3-stable-linux-amd64.tgz https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar xvzf /tmp/ngrok-v3-stable-linux-amd64.tgz -C /tmp
sudo mv /tmp/ngrok /usr/local/bin
ngrok --version
```

Configure ngrok
```bash
ngrok config add-authtoken <YOUR_AUTH_TOKEN>
```

Run voice proxy server
```bash
docker build --no-cache -t voice-proxy .
docker run -it -p 8080:8080 --env ENVIRONMENT_NAME=prod voice-proxy
```

## Create Stripe Product
1. Go to Stripe Dashboard -> Products -> Create Product
2. Go to Developers -> Webhooks -> Add endpoint
3. Enter the webhook URL: https://<API_GATEWAY_URL>/webhook/stripe
4. Select the events to subscribe to:
    - `payment_intent.succeeded`
    - `payment_intent.payment_failed`
    - `customer.subscription.created`
    - `customer.subscription.updated`
    - `invoice.upcoming`
    - `invoice.paid`
    - `invoice.payment_failed`
