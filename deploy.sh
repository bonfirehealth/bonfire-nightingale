#!/bin/bash

# Check if .env file exists
if [ ! -f .env ]; then
  echo ".env file not found!"
  exit 1
fi

# Load environment variables from .env file safely
set -a
source .env
set +a

# Deploy all stacks using cdk
cdk deploy --all
