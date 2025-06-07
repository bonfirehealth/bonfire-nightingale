import openai
import json
from config import OPENAI_API_KEY, SYSTEM_PROMPT, logger
from datetime import datetime, timedelta

openai.api_key = OPENAI_API_KEY

def default_serializer(obj):
    """Default serializer for datetime objects"""
    if isinstance(obj, (datetime, timedelta)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def build_ai_context(conversation_id, user, conversation_history, trial_status, user_message):
    """Build context string for AI system prompt"""
    # Context for openai system prompt
    user_name = user.get("name", "Unknown")
    context = f"""
    ================= START CONVERSATION CONTEXT =================
    Conversation ID: {conversation_id}
    User ID: {user["id"]}
    User WhatsApp ID: {user["whatsapp_id"]}
    User Phone: {user["phone"]}
    User Email: {user["email"]}
    User Postal Code: {user["postal_code"]}
    User Coaching Session Count: {user["coaching_session_count"]}
    User Last Coaching Date: {user["last_coaching_date"]}
    User Monthly Summary Option: {user["monthly_summary_option"]}
    User Subscription Status: {user["subscription_status"]}
    User Trial Start Date: {user["trial_start_date"]}
    Conversation history: {conversation_history}

    ---
    User name: {user_name}
    Current user message: {user_message}
    ================= END CONVERSATION CONTEXT =================
    """
    context = json.dumps(context, default=default_serializer)
    return context

def create_fallback_response():
    """Create safe fallback response if AI fails"""
    return {
        "message": "I'm having a moment of technical difficulty. Can you please try again?",
        "action": "general_purpose",
        "mode": "undefined",
        "data": {},
        "next_step": None,
        "flags": {"crisis_detected": False, "needs_escalation": False, "session_complete": False}
    }
