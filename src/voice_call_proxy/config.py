import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if os.environ.get("ENVIRONMENT_NAME") == "dev" else logging.INFO)

# Add console handler if no handlers are configured
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

# --- Database ---
DB_HOST="nightingaledatabasestack-d-databasecluster68fc2945-rwipeod2ffaj.cluster-cd0csowcqlz1.ap-southeast-1.rds.amazonaws.com"
DB_PORT=5432
DB_NAME="nightingale_dev"
DB_USER="bonfire"
DB_PASSWORD="Yl_CnHIYpT0e,Bw684Tipji.xsWkb4"

# OpenAI
OPENAI_API_KEY="sk-bonfire-D8ucpXWY5s3fHFxcoyOqT3BlbkFJuXxjuFwUwUbnrWXLzKSU"
OPENAI_ASSISTANT_ID="asst_KzGUPJknnqGRy5rrKqkmeSQc"

# WATI
WATI_API_ENDPOINT="https://live-mt-server.wati.io/397781"
WATI_ACCESS_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIxNmIzZDUwNi02ZjdiLTRjOWItYWI0Ny1kODI3MjkwYWQ1OTUiLCJ1bmlxdWVfbmFtZSI6InRhbW52aHVzdGNjQGdtYWlsLmNvbSIsIm5hbWVpZCI6InRhbW52aHVzdGNjQGdtYWlsLmNvbSIsImVtYWlsIjoidGFtbnZodXN0Y2NAZ21haWwuY29tIiwiYXV0aF90aW1lIjoiMDMvMjUvMjAyNSAxMzoxODoyNyIsInRlbmFudF9pZCI6IjM5Nzc4MSIsImRiX25hbWUiOiJtdC1wcm9kLVRlbmFudHMiLCJodHRwOi8vc2NoZW1hcy5taWNyb3NvZnQuY29tL3dzLzIwMDgvMDYvaWRlbnRpdHkvY2xhaW1zL3JvbGUiOiJBRE1JTklTVFJBVE9SIiwiZXhwIjoyNTM0MDIzMDA4MDAsImlzcyI6IkNsYXJlX0FJIiwiYXVkIjoiQ2xhcmVfQUkifQ.o6dWvxYf1eGRKrgbSW-hcWu1jzdjhtThobp1VBvV4zI"

# --- Twilio ---
TWILIO_PHONE_NUMBER="+6531052531"
TWILIO_ACCOUNT_SID="AC43d2fd2b88bd8be1c8d4e4bd9d3f850e"
TWILIO_AUTH_TOKEN="8b5d7de73787f78cb644191eb4b5dc19"
TARGET_PHONE="84983866260"
VOICE_CALL_ID="1"

# Elevenlabs (for voice call proxy)
ELEVENLABS_API_KEY="sk_e34c41b711babb30154d03e23853f6d113b306484297e538"
ELEVENLABS_ENGLISH_AGENT_ID="zvgUzjrGRpJmukxcVmGC"
ELEVENLABS_CHINESE_AGENT_ID="agent_01jyndm70ben6aqjmc13mg3842"
ELEVENLABS_POSTCALL_WEBHOOK_SECRET="wsec_33f0c57f1627ab9f52cb63ad2c6f21dc1d9f51d60d04b72c585a7525571a2479"

MAX_CALL_DURATION_SECONDS=1800
