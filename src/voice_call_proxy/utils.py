import os

import aiohttp
import requests

from config import (
    logger, ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, PUBLIC_DOMAIN
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

def get_public_domain():
    """Returns public domain of the Fargate task"""
    return PUBLIC_DOMAIN