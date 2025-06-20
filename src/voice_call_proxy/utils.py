import os

import aiohttp
import requests

from config import (
    logger, ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID
)

# Helper function to get signed URL for authenticated conversations
async def get_signed_url():
    # Check for required environment variables

    if not all([ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID]):
        raise ValueError("Missing required environment variables")

    try:
        url = f"https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id={ELEVENLABS_AGENT_ID}"
        headers = {"xi-api-key": ELEVENLABS_API_KEY}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("signed_url")
                else:
                    error_message = await response.text()
                    logger.error(f"Error getting signed URL: Status code {response.status}, Message: {error_message}")
                    return None  # Or raise an exception, depending on how you want to handle errors
    except Exception as e:
        logger.error(f"Error getting signed URL: {e}")
        raise

async def get_agent_system_prompt():
    try:
        url = f"https://api.elevenlabs.io/v1/convai/agents/{ELEVENLABS_AGENT_ID}"
        headers = {"xi-api-key": ELEVENLABS_API_KEY}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    conversation_config = data.get("conversation_config")
                    system_prompt = conversation_config.get("agent", {}).get("prompt", {}).get("prompt", "")
                    return system_prompt
                else:
                    error_message = await response.text()
                    logger.error(f"Error getting agent info: Status code {response.status}, Message: {error_message}")
                    return None  # Or raise an exception, depending on how you want to handle errors
    except Exception as e:
        logger.error(f"Error getting agent info: {e}")
        raise

def get_fargate_public_ip():
    """Queries the ECS Task Metadata Endpoint to get the public IP."""
    # Endpoint v4 là endpoint mới và được khuyến nghị
    metadata_url = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if not metadata_url:
        logger.warning("Not running in an ECS Fargate environment with V4 metadata. Returning None.")
        return None
    
    try:
        # Lấy metadata của task
        response = requests.get(f"{metadata_url}/task", timeout=2)
        response.raise_for_status()
        task_metadata = response.json()
        
        # Tìm network interface và IP
        network_interface = task_metadata.get("Containers")[0].get("Networks")[0]
        eni_id = network_interface.get("NetworkInterfaceId")

        # Lấy metadata của ENI đó
        import boto3

        ec2 = boto3.client('ec2')
        response = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
        public_ip = response['NetworkInterfaces'][0]['Association'].get('PublicIp')

        logger.info(f"Successfully discovered public IP: {public_ip}")
        return public_ip
    except Exception as e:
        logger.error(f"Could not discover Fargate public IP: {e}")
        return None
