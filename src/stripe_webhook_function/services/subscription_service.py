import stripe
from typing import Dict, Any
from psycopg2.extras import RealDictCursor

from services import database_service as db
from config import logger

def handle_subscription_created(event_data: Dict[str, Any]) -> None:
    """Handle new subscription event"""
    subscription = event_data['object']
    customer_id = subscription.get('customer')
    
    try:
        # Get customer details from Stripe
        customer = stripe.Customer.retrieve(customer_id)
        
        conn = db.get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                INSERT INTO subscriptions (
                    stripe_subscription_id,
                    stripe_customer_id,
                    customer_email,
                    status,
                    current_period_start,
                    current_period_end,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (stripe_subscription_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    current_period_start = EXCLUDED.current_period_start,
                    current_period_end = EXCLUDED.current_period_end,
                    updated_at = NOW()
            """, (
                subscription['id'],
                customer_id,
                customer.get('email'),
                subscription['status'],
                subscription['current_period_start'],
                subscription['current_period_end']
            ))
            conn.commit()
            logger.info(f"Subscription {subscription['id']} recorded successfully")
            
    except Exception as e:
        logger.error(f"Error processing subscription: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def handle_subscription_cancelled(event_data: Dict[str, Any]) -> None:
    """Handle subscription cancellation event"""
    subscription = event_data['object']
    
    try:
        conn = db.get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE subscriptions 
                SET status = 'canceled', 
                    updated_at = NOW()
                WHERE stripe_subscription_id = %s
            """, (subscription['id'],))
            conn.commit()
            logger.info(f"Subscription {subscription['id']} marked as canceled")
            
    except Exception as e:
        logger.error(f"Error canceling subscription: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()
