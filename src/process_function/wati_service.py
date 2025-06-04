import logging
from config import app_conf

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- WATI API Helper ---
def send_wati_message(recipient_id: str, message_text: str) -> bool:
    try:
        logger.info(f"Sending WATI message: `{message_text}` to {recipient_id}")
        wati_access_token = app_conf.get('WATI_ACCESS_TOKEN')
        if not wati_access_token:
            raise ValueError("WATI Access Token not found or not configured in application secrets.")
        
        wati_api_endpoint = app_conf.get('WATI_API_ENDPOINT')
        if not wati_api_endpoint:
            raise ValueError("WATI API Endpoint not found or not configured in application secrets.")
        
        logger.info(f"WATI API Endpoint: {wati_api_endpoint}")
        import requests
        headers = {
            "Content-type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {wati_access_token}"
        }
        payload = {"messageText": message_text}
        url = f"{wati_api_endpoint}/api/v1/sendSessionMessage/{recipient_id}"
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"Sent WATI message to {recipient_id}: {message_text}")
        return True
    except Exception as e:
        logger.error(f"Error sending WATI message: {e}")
        return False
