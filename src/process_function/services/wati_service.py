from config import app_conf, logger
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests


# --- WATI API Helper ---
def send_text_message(recipient_id: str, message_text: str) -> bool:
    """
    Send a message to a WhatsApp user using WATI API with retry on network errors.

    Args:
        recipient_id (str): The WhatsApp ID of the recipient.
        message_text (str): The text message to send.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    try:
        logger.info(f"Sending WATI message: `{message_text}` to {recipient_id}")
        wati_access_token = app_conf.get('WATI_ACCESS_TOKEN')
        if not wati_access_token:
            raise ValueError("WATI Access Token not found or not configured in application secrets.")
        
        wati_api_endpoint = app_conf.get('WATI_API_ENDPOINT')
        if not wati_api_endpoint:
            raise ValueError("WATI API Endpoint not found or not configured in application secrets.")
        
        logger.debug(f"WATI API Endpoint: {wati_api_endpoint}")
        
        # Set up retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,  # 1 second wait time between retries, then 2s, 4s...
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        http = requests.Session()
        http.mount("https://", adapter)
        http.mount("http://", adapter)

        headers = {
            "Content-type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {wati_access_token}"
        }
        payload = {"messageText": message_text}
        url = f"{wati_api_endpoint}/api/v1/sendSessionMessage/{recipient_id}"

        response = http.post(url, data=payload, headers=headers)
        response.raise_for_status()

        logger.info(f"Sent WATI message to {recipient_id}: {message_text}")
        return True

    except Exception as e:
        logger.error(f"Error sending WATI message: {e}")
        return False


def send_template_message(recipient_id: str, template_name: str,
                          broadcast_name: str, parameters: dict = None) -> bool:
    """
    Send a template message to a WhatsApp user using WATI API with retry on network errors.

    Args:
        recipient_id (str): The WhatsApp ID of the recipient.
        template_name (str): The name of the template to send.
        broadcast_name (str): The name of the broadcast to send.
        parameters (dict): The parameters to send with the template.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    try:
        logger.info(f"Sending WATI template message to {recipient_id}")
        wati_access_token = app_conf.get('WATI_ACCESS_TOKEN')

        if not wati_access_token:
            raise ValueError("WATI Access Token not found or not configured in application secrets.")
        
        wati_api_endpoint = app_conf.get('WATI_API_ENDPOINT')
        if not wati_api_endpoint:
            raise ValueError("WATI API Endpoint not found or not configured in application secrets.")
        
        logger.debug(f"WATI API Endpoint: {wati_api_endpoint}")

        # Set up retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,  # 1 second wait time between retries, then 2s, 4s...
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        http = requests.Session()
        http.mount("https://", adapter)
        http.mount("http://", adapter)

        headers = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {wati_access_token}",
        }
        data = {
            "template_name": template_name,
            "broadcast_name": broadcast_name
        }
        if parameters:
            data["parameters"] = parameters
        params = {
            "whatsappNumber": recipient_id
        }
        url = f"{wati_api_endpoint}/api/v1/sendTemplateMessage"

        response = http.post(url, json=data, params=params, headers=headers)
        response.raise_for_status()

        logger.info(f"Sent WATI template message to {recipient_id}")
        return True

    except Exception as e:
        logger.error(f"Error sending WATI template message: {e}")
        return False