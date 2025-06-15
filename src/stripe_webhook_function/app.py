import json

import stripe
from psycopg2.extras import RealDictCursor

from services import wati_service as wati, database_service as db
from config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, logger

def lambda_handler(event, context):
    """Main Lambda handler for Stripe webhooks"""
    try:
        # Get application secrets (including Stripe keys)
        stripe.api_key = STRIPE_SECRET_KEY
        endpoint_secret = STRIPE_WEBHOOK_SECRET
        
        # Get the raw body and signature
        body = event.get('body', '')
        signature = event.get('headers', {}).get('stripe-signature', '')
        
        if not signature:
            logger.error("Missing Stripe signature")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing signature'})
            }
        
        # Verify the webhook signature
        if not verify_stripe_signature(body, signature, endpoint_secret):
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid signature'})
            }
        
        # Parse the event
        try:
            stripe_event = json.loads(body)
        except json.JSONDecodeError:
            logger.error("Invalid JSON payload")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid JSON'})
            }
        
        # Handle the event
        event_type = stripe_event['type']
        event_data = stripe_event['data']
        
        logger.info(f"Received Stripe event: {event_type}")
        
        if event_type == 'checkout.session.completed':
            handle_payment_success(event_data)
        elif event_type == 'payment_intent.payment_failed':
            handle_payment_failed(event_data)
        elif event_type == 'customer.subscription.created':
            handle_subscription_created(event_data)
        elif event_type == 'customer.subscription.updated':
            handle_subscription_created(event_data)  # Reuse the same handler
        elif event_type == 'customer.subscription.deleted':
            # Handle subscription cancellation
            subscription = event_data['object']
            conn = db.get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE subscriptions 
                        SET status = 'canceled', updated_at = NOW()
                        WHERE stripe_subscription_id = %s
                    """, (subscription['id'],))
                    conn.commit()
            finally:
                conn.close()
        else:
            logger.info(f"Unhandled event type: {event_type}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'received': True})
        }
        
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }


def verify_stripe_signature(payload, signature, endpoint_secret):
    """Verify Stripe webhook signature"""
    try:
        stripe.Webhook.construct_event(payload, signature, endpoint_secret)
        return True
    except ValueError:
        logger.error("Invalid payload")
        return False
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid signature")
        return False

def handle_payment_success(event_data):
    """Handle successful payment event"""
    logger.info(f"Processing payment success: {event_data['object']['id']}")

    # Get the original parent ID from the event data
    
    # Extract payment information
    payment_intent = event_data['object']
    customer_id = payment_intent.get('customer')
    amount = payment_intent.get('amount')
    currency = payment_intent.get('currency')
    payment_method = payment_intent.get('payment_method')
    
    # Get customer details from Stripe
    if customer_id:
        try:
            customer = stripe.Customer.retrieve(customer_id)
            customer_email = customer.get('email')
            customer_name = customer.get('name')
        except Exception as e:
            logger.error(f"Error retrieving customer: {e}")
            customer_email = None
            customer_name = None
    else:
        customer_email = None
        customer_name = None
    
    # Store payment information in database
    try:
        conn = db.get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                INSERT INTO payments (
                    stripe_payment_intent_id,
                    customer_email,
                    customer_name,
                    amount,
                    currency,
                    payment_type,
                    payment_method,
                    status,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (stripe_payment_intent_id) 
                DO UPDATE SET 
                    status = EXCLUDED.status,
                    updated_at = NOW()
            """, (
                payment_intent['id'],
                customer_email,
                customer_name,
                amount,
                currency,
                'subscription',
                payment_method,
                'succeeded'
            ))

            # Update subscription status if applicable
            cursor.execute("UPDATE parents SET status = 'active' WHERE  = %s", (payment_intent['id'],))
            conn.commit()
            logger.info(f"Payment {payment_intent['id']} recorded successfully")
        
        # Send WATI message to user
        if customer_email:
            # TODO:
            wati.send_text_message(customer_email, "Thank you for your payment! Your subscription is now active.")
            
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def handle_payment_failed(event_data):
    """Handle failed payment event"""
    logger.info(f"Processing payment failure: {event_data['id']}")
    
    payment_intent = event_data['object']
    
    try:
        conn = db.get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                UPDATE payments 
                SET status = %s, 
                    failure_reason = %s, 
                    updated_at = NOW()
                WHERE stripe_payment_intent_id = %s
            """, (
                'failed',
                payment_intent.get('last_payment_error', {}).get('message', 'Unknown error'),
                payment_intent['id']
            ))
            conn.commit()
            logger.info(f"Payment failure {payment_intent['id']} recorded")
        
        # Send WATI message to user
        if customer_email:
            # TODO:
            wati.send_text_message(customer_email, "Payment failed. Please try again.")
            
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def handle_subscription_created(event_data):
    """Handle new subscription event"""
    logger.info(f"Processing subscription created: {event_data['id']}")
    
    subscription = event_data['object']
    customer_id = subscription.get('customer')
    
    try:
        # Get customer details
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
        if conn:
            conn.close()
