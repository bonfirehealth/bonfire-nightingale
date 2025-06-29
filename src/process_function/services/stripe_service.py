import stripe
from config import (
    STRIPE_SECRET_KEY, STRIPE_MONTHLY_PRICE_ID, STRIPE_YEARLY_PRICE_ID,
    STRIPE_WEBHOOK_SUCCESS_URL, STRIPE_WEBHOOK_CANCEL_URL,
    logger
)

def create_checkout_session(user_id: int | str, subscription_type: str) -> stripe.checkout.Session:
    """
    Creates a checkout session for a user.
    
    Args:
        user_id (int | str): The ID of the user.
        subscription_type (str): The type of subscription.
    
    Returns:
        dict: The checkout session object.
    """
    try:
        logger.info(f"Creating checkout session for user {user_id}")
        logger.debug(f"Subscription type: {subscription_type}")
        logger.debug(f"Monthly price ID: {STRIPE_MONTHLY_PRICE_ID}")
        logger.debug(f"Yearly price ID: {STRIPE_YEARLY_PRICE_ID}")

        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price": STRIPE_MONTHLY_PRICE_ID if subscription_type == "monthly" else STRIPE_YEARLY_PRICE_ID,
                "quantity": 1,
            }],
            client_reference_id=str(user_id),
            success_url=STRIPE_WEBHOOK_SUCCESS_URL,
            cancel_url=STRIPE_WEBHOOK_CANCEL_URL,
        )
        logger.info(f"Checkout session created for user {user_id}: {session}")
        return session
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise Exception(f"Error creating checkout session: {e}")