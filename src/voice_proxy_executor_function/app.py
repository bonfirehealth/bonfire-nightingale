import logging
import traceback
from typing import Dict, Any
from twilio.rest import Client

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def lambda_handler(event: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # Validate required parameters
        twilio_phone_number = event.get("twilio_phone_number")
        twilio_account_sid = event.get("twilio_account_sid")
        twilio_auth_token = event.get("twilio_auth_token")
        voice_language = event.get("voice_language")
        domain = event.get("domain")
        target_phone = event.get("target_phone")
        voice_call_id = event.get("voice_call_id")

        if not twilio_account_sid:
            raise ValueError("Missing required parameters: twilio_account_sid")

        if not twilio_auth_token:
            raise ValueError("Missing required parameters: twilio_auth_token")

        if not domain:
            raise ValueError("Missing required parameters: domain")

        if not target_phone:
            raise ValueError("Missing required parameters: target_phone")

        if not voice_call_id:
            raise ValueError("Missing required parameters: voice_call_id")

        client = Client(twilio_account_sid, twilio_auth_token)

        target_phone_with_plus = "+" + target_phone if not target_phone.startswith("+") else target_phone
        outbound_twiml = (
            f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            f"<Response>"
            f"  <Connect>"
            f"    <Stream url=\"wss://{domain}/media-stream/{target_phone_with_plus}/{voice_call_id}/{voice_language}\" />"
            f"  </Connect>"
            f"</Response>"
        )
        call = client.calls.create(
            record=False,
            from_=twilio_phone_number,
            to=target_phone_with_plus,
            twiml=outbound_twiml,
        )
        logger.info(f"Made a call to {target_phone_with_plus} with SID: {call.sid}")

        return {
            "statusCode": 200,
            "body": call.sid
        }

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}\n{traceback.format_exc()}")
        return {
            "statusCode": 400,
            "body": f"Validation error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Unexpected error in lambda_handler: {str(e)}\n{traceback.format_exc()}")
        return {
            "statusCode": 500,
            "body": f"Unexpected error: {str(e)}"
        }