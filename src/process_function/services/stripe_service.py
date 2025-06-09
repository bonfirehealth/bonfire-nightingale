import stripe
from config import STRIPE_SECRET_KEY, logger

def create_checkout_session(user_id: str) -> object:
    """
    Creates a checkout session for a user.
    
    Args:
        user_id (int): The ID of the user.
    
    Returns:
        dict: The checkout session object.
    """
    try:
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode='subscription',
            line_items=[{
                'price': 'price_1MotwRLkdIwHu7ixYcPLm5uZ',
                'quantity': 1,
            }],
            success_url='https://yourdomain.com/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://yourdomain.com/cancel',
            client_reference_id=user_id,
        )
        return session
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        return None