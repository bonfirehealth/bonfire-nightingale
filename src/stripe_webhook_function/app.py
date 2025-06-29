import os
import json
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from jinja2 import Environment, FileSystemLoader

from config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, logger
from stripe_webhook_handler import StripeWebhookHandler

# Initialize Jinja2 environment
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

# Initialize Stripe webhook handler
stripe_webhook_handler = StripeWebhookHandler(
    stripe_secret=STRIPE_SECRET_KEY,
    webhook_secret=STRIPE_WEBHOOK_SECRET
)

def lambda_handler(event, context):
    """Main Lambda handler for all incoming requests"""
    try:
        logger.info("Receiving an event from Stripe")
        logger.debug(f"Event: {event}")
        path = event.get("rawPath", "")
        method = event.get("requestContext", {}).get("http", {}).get("method", "")

        # Route requests to appropriate handlers
        if path == "/webhook/stripe" and method == "POST":
            # Extract signature and body for Stripe webhook
            body = event.get('body', '')
            signature = event.get('headers', {}).get('stripe-signature', '')
            return stripe_webhook_handler.handle_webhook(body, signature)

        # Handle success page
        elif path == "/stripe/success" and method == "GET":
            session_id = get_session_id(event)
            logger.debug(f"Handling success page with session ID: {session_id}")
            return render_template("success.html", session_id=session_id)

        # Handle cancel page
        elif path == "/stripe/cancel" and method == "GET":
            session_id = get_session_id(event)
            logger.debug(f"Handling cancel page with session ID: {session_id}")
            return render_template("cancel.html", session_id=session_id)

        # 404 for unknown routes
        else:
            logger.debug(f"Unknown route: {path}")
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Not found"})
            }

    except Exception as e:
        logger.error(f"Error in lambda_handler: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }


def render_template(template_name: str, **context) -> dict:
    """Helper function to render HTML templates"""
    try:
        html = env.get_template(template_name).render(**context)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/html"},
            "body": html
        }
    except Exception as e:
        logger.error(f"Error rendering template {template_name}: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Error loading page"})
        }


def get_session_id(event: dict) -> str:
    """Extract session ID from event"""
    return event.get('queryStringParameters', {}).get('session_id', '')