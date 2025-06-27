import os

import aiohttp
import requests

from config import (
    logger, PUBLIC_DOMAIN, ELEVENLABS_ENGLISH_AGENT_ID,
    ELEVENLABS_CHINESE_AGENT_ID
)

# Helper function to get signed URL for authenticated conversations
async def get_signed_url(api_key: str, agent_id: str):
    # Check for required environment variables

    if not all([api_key, agent_id]):
        raise ValueError("Missing required environment variables")

    try:
        url = f"https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id={agent_id}"
        headers = {"xi-api-key": api_key}

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

async def get_agent_system_prompt(api_key: str, agent_id: str):
    try:
        url = f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}"
        headers = {"xi-api-key": api_key}

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

def get_agent_id_by_language(language: str):
    if language == "english":
        return ELEVENLABS_ENGLISH_AGENT_ID
    elif language == "chinese":
        return ELEVENLABS_CHINESE_AGENT_ID
    else:
        return None