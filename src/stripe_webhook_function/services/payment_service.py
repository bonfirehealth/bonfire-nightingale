from typing import Dict, Any
from psycopg2.extras import RealDictCursor

from services import database_service as db
from config import logger

def handle_payment_success(event_data: Dict[str, Any]) -> None:
    """Handle successful payment event"""
    logger.info(f"Processing payment success: {event_data['object']['id']}")
    
    try:
        # TODO: Uncomment and implement payment processing logic
        # whatsapp_id = event_data['object']['client_reference_id']
        # message = "Thank you for your payment! Your subscription is now active."
        # wati.send_text_message(whatsapp_id, message)
        pass
    except Exception as e:
        logger.error(f"Error processing payment success: {e}")
        raise

def handle_payment_failed(event_data: Dict[str, Any]) -> None:
    """Handle failed payment event"""
    logger.info(f"Processing payment failure: {event_data['id']}")
    
    try:
        payment_intent = event_data['object']
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
            
    except Exception as e:
        logger.error(f"Database error in handle_payment_failed: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()
