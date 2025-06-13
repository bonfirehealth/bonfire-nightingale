import stripe
from config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SUCCESS_URL, STRIPE_WEBHOOK_CANCEL_URL, logger

def create_checkout_session(user_id: int | str) -> stripe.checkout.Session:
    """
    Creates a checkout session for a user.
    
    Args:
        user_id (int | str): The ID of the user.
    
    Returns:
        dict: The checkout session object.
    """
    try:
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price": STRIPE_PRICE_ID,
                "quantity": 1,
            }],
            success_url=f"{STRIPE_WEBHOOK_SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=STRIPE_WEBHOOK_CANCEL_URL,
            client_reference_id=user_id,
        )
        return session
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise