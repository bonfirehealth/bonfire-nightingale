from typing import Dict, Any
import stripe
from psycopg2.extras import RealDictCursor

from services import database_service as db
from config import logger, STRIPE_SECRET_KEY

stripe.api_key = STRIPE_SECRET_KEY

def handle_subscription_created(event_data: Dict[str, Any]) -> None:
    """Handle new subscription event"""
    subscription = event_data['object']
    customer_id = subscription.get('customer')

    current_period_start = None
    current_period_end = None

    if "items" in subscription:
        current_period_start = subscription['items']['data'][0]['current_period_start']
        current_period_end = subscription['items']['data'][0]['current_period_end']
    
    if not current_period_start or not current_period_end:
        logger.error("Could not find current period start or end in subscription")
        raise Exception("Could not find current period start or end in subscription")
    
    try:
        customer = stripe.Customer.retrieve(customer_id)
        logger.info(f"Customer {customer_id} retrieved successfully")

        conn = db.get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                INSERT INTO subscriptions (
                    stripe_subscription_id,
                    stripe_customer_id,
                    customer_email,
                    stripe_status,
                    current_period_start,
                    current_period_end
                ) VALUES (%s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s))
                ON CONFLICT (stripe_subscription_id)
                DO UPDATE SET
                    stripe_status = EXCLUDED.stripe_status,
                    current_period_start = EXCLUDED.current_period_start,
                    current_period_end = EXCLUDED.current_period_end
            """, (
                subscription['id'],
                customer_id,
                customer['email'],
                subscription['status'],
                subscription['items']['data'][0]['current_period_start'],
                subscription['items']['data'][0]['current_period_end'],
            ))
            conn.commit()
            logger.info(f"Subscription {subscription['id']} recorded successfully")
            
    except Exception as e:
        logger.error(f"Error processing subscription: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()


def handle_subscription_deleted(event_data: Dict[str, Any]) -> None:
    """Handle subscription deletion event"""
    subscription = event_data['object']
    
    try:
        conn = db.get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE subscriptions 
                SET status = 'cancelled'
                WHERE stripe_subscription_id = %s
            """, (subscription['id'],))
            conn.commit()
            logger.info(f"Subscription {subscription['id']} deleted successfully")
            
    except Exception as e:
        logger.error(f"Error deleting subscription: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()


def handle_invoice_payment_failed(event_data: Dict[str, Any]) -> None:
    """Handle invoice payment failed event"""
    invoice = event_data['object']
    
    try:
        # Send message to user
        message = "Invoice payment failed. Please try again or contact support for assistance."
        wati.send_text_message(invoice['customer'], message)
    except Exception as e:
        logger.error(f"Error processing invoice payment failed: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()
