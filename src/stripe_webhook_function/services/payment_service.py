from typing import Dict, Any
from psycopg2.extras import RealDictCursor

from services import database_service as db
from services import wati_service as wati
from config import logger


def handle_checkout_session_completed(event_data: Dict[str, Any]) -> None:
    """Handle checkout session completed event"""
    logger.info(f"Processing checkout session completed: {event_data['object']['id']}")
    
    try:
        event_obj = event_data['object']

        # Add a new payment record
        add_payment(event_obj)

        # Update parent subscription status
        parent_info = update_parent_subscription(event_obj)

        # Send reply message to parent
        reply_to_user = build_reply_message(event_obj)
        wati.send_text_message(parent_info['whatsapp_id'], reply_to_user)
    except Exception as e:
        logger.error(f"Error processing checkout: {e}")
        raise


def add_payment(event_obj: Dict[str, Any]) -> None:
    """Update payment status in database"""
    try:
        parent_id = int(event_obj['client_reference_id'])
        custom_data = event_obj['metadata']
        plan_id = int(custom_data['plan_id'])

        conn = db.get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                INSERT INTO payments (
                    parent_id,
                    plan_id,
                    stripe_invoice_id,
                    amount,
                    currency,
                    payment_method,
                    status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                parent_id,
                plan_id,
                event_obj['invoice'],
                event_obj['amount_total'],
                event_obj['currency'],
                'stripe',
                'succeeded'
            ))
            conn.commit()
            logger.info(f"Payment {event_obj['id']} marked as {event_obj['status']}")
            
    except Exception as e:
        logger.error(f"Database error in add_payment: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()


def update_parent_subscription(event_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Update parent subscription in database

    We don't need to delete the scheduled trial nudge because it will not be
    triggered if the parent has a paid subscription.
    
    Args:
        event_obj (Dict[str, Any]): The event object from Stripe.
    
    Returns:
        Dict[str, Any]: The updated parent subscription.
    """
    try:
        parent_id = int(event_obj["metadata"]["parent_id"])
        conn = db.get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Update parent subscription status, no more trial plan
            # Set sent_trial_expiry to TRUE to prevent sending trial expiry message
            cursor.execute("""
                UPDATE parents 
                SET subscription_status = 'active_paid', 
                    sent_trial_expiry = TRUE
                WHERE id = %s
                RETURNING *
            """, (parent_id,))
            conn.commit()
            logger.info(f"Parent {parent_id} subscription updated")
            return cursor.fetchone() 
    except Exception as e:
        logger.error(f"Database error in update_parent_subscription: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()


def build_reply_message(event_obj: Dict[str, Any]) -> str:
    """Build reply message for parent"""
    try:
        plan_id = event_obj['metadata']['plan_id']

        # Get subscription plan info from database using price_id
        conn = db.get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get price ID from the event object
            cursor.execute("SELECT * FROM subscription_plans WHERE id = %s", (plan_id,))
            subscription_plan = cursor.fetchone()
            conn.close()
            
            if subscription_plan:
                return f"Payment successfully processed for {subscription_plan['name']}. Your subscription is now active. Thank you for choosing our service!"
            return "Payment successfully processed. Your subscription is now active. Thank you for choosing our service!"
            
    except Exception as e:
        logger.error(f"Error in build_reply_message: {e}")
        return "Payment successfully processed. Your subscription is now active. Thank you for choosing our service!"