import json
import logging
import stripe
from typing import Dict, Any, Optional

from services import payment_service, subscription_service
from config import logger

class StripeWebhookHandler:
    def __init__(self, stripe_secret: str, webhook_secret: str):
        self.stripe_secret = stripe_secret
        self.webhook_secret = webhook_secret
        stripe.api_key = stripe_secret

    def handle_webhook(self, event_data: Dict[str, Any], signature: str) -> Dict[str, Any]:
        """Main handler for Stripe webhooks"""
        try:
            if not self._verify_signature(event_data, signature):
                return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid signature'})}

            event = json.loads(event_data) if isinstance(event_data, str) else event_data
            event_type = event.get('type', '')
            event_data = event.get('data', {})

            logger.info(f"Received Stripe event: {event_type}")

            if event_type == 'checkout.session.completed':
                payment_service.handle_payment_success(event_data)
            # Uncomment and implement other event handlers as needed
            # elif event_type == 'payment_intent.payment_failed':
            #     payment_service.handle_payment_failed(event_data)
            # elif event_type in ['customer.subscription.created', 'customer.subscription.updated']:
            #     subscription_service.handle_subscription_created(event_data)
            # elif event_type == 'customer.subscription.deleted':
            #     subscription_service.handle_subscription_cancelled(event_data)
            else:
                logger.info(f"Unhandled event type: {event_type}")

            return {'statusCode': 200, 'body': json.dumps({'received': True})}

        except json.JSONDecodeError:
            logger.error("Invalid JSON payload")
            return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid JSON'})}
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return {'statusCode': 500, 'body': json.dumps({'error': 'Internal server error'})}

    def _verify_signature(self, payload: str, signature: str) -> bool:
        """Verify Stripe webhook signature"""
        try:
            stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            return True
        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            return False
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            return False
