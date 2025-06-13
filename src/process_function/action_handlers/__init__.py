import traceback
from psycopg2.extensions import cursor as Psycopg2Cursor

from config import logger
from .handlers import ACTION_HANDLERS

def execute_action(action: str, cursor: Psycopg2Cursor, parent_id: int, ai_response: dict) -> None:
    """
    Execute the specified action with proper error handling.
    
    Args:
        action: Action type to execute
        cursor: Database cursor
        parent_id: Parent's ID
        ai_response: Response data from AI service containing action-specific data
        
    Raises:
        Exception: Re-raises any exceptions for transaction rollback
    """
    try:
        handler = ACTION_HANDLERS.get(action)
        if not handler:
            logger.error(f"Unknown action type: '{action}' for parent_id: {parent_id}")
            return
            
        handler(cursor, parent_id, ai_response)
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(
            f"Error executing action '{action}' for parent {parent_id}: {e}\n"
            f"Traceback:\n{error_traceback}"
        )
        raise