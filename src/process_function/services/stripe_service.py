import stripe
from services import database_service as db
from psycopg2.extras import RealDictCursor
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

        price_id = STRIPE_MONTHLY_PRICE_ID if subscription_type == "monthly" else STRIPE_YEARLY_PRICE_ID
        plan_id = get_plan_id(price_id)

        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            client_reference_id=str(user_id),
            metadata={
                "parent_id": str(user_id),
                "plan_id": plan_id
            },
            success_url=STRIPE_WEBHOOK_SUCCESS_URL,
            cancel_url=STRIPE_WEBHOOK_CANCEL_URL,
        )
        logger.info(f"Checkout session created for user {user_id}: {session}")
        return session
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise Exception(f"Error creating checkout session: {e}")


def get_plan_id(stripe_price_id: str) -> str:
    """
    Returns the plan ID for the given Stripe price ID.
    
    Args:
        stripe_price_id (str): The Stripe price ID.
    
    Returns:
        str: The Stripe price ID.
    """
    try:
        conn = db.get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT *
                FROM subscription_plans
                WHERE stripe_price_id = %s
            """, (stripe_price_id,))
            plan = cursor.fetchone()
            return plan['id']
    except Exception as e:
        logger.error(f"Error getting plan ID: {e}")
        raise Exception(f"Error getting plan ID: {e}")