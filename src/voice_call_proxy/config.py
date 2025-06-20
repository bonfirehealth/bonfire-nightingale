import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if os.environ.get("ENVIRONMENT_NAME") == "dev" else logging.INFO)

# # --- Database ---
# DB_HOST = os.environ.get("DB_HOST")
# DB_PORT = os.environ.get("DB_PORT")
# DB_NAME = os.environ.get("DB_NAME")
# DB_USER = os.environ.get("DB_USER")
# DB_PASSWORD = os.environ.get("DB_PASSWORD")

# # --- Twilio ---
# TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
# TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
# TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
# TARGET_PHONE = os.environ.get("TARGET_PHONE")
# VOICE_CALL_ID = os.environ.get("VOICE_CALL_ID")

# # Elevenlabs (for voice call proxy)
# ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
# ELEVENLABS_AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID")
# ELEVENLABS_WEBHOOK_SECRET = os.environ.get("ELEVENLABS_WEBHOOK_SECRET")

# --- Database ---
DB_HOST = "nightingaledatabasestack-d-databasecluster68fc2945-rwipeod2ffaj.cluster-cd0csowcqlz1.ap-southeast-1.rds.amazonaws.com"
DB_PORT = 5432
DB_NAME = "nightingale_dev"
DB_USER = "bonfire"
DB_PASSWORD = "Yl_CnHIYpT0e,Bw684Tipji.xsWkb4"

# --- Twilio ---
TWILIO_PHONE_NUMBER="+6531052531"
TWILIO_ACCOUNT_SID="AC43d2fd2b88bd8be1c8d4e4bd9d3f850e"
TWILIO_AUTH_TOKEN="8b5d7de73787f78cb644191eb4b5dc19"
TARGET_PHONE = "84983866260"
VOICE_CALL_ID = "1"

# Elevenlabs (for voice call proxy)
ELEVENLABS_API_KEY="sk_e34c41b711babb30154d03e23853f6d113b306484297e538"
ELEVENLABS_AGENT_ID="zvgUzjrGRpJmukxcVmGC"
ELEVENLABS_POSTCALL_WEBHOOK_SECRET="wsec_33f0c57f1627ab9f52cb63ad2c6f21dc1d9f51d60d04b72c585a7525571a2479"