import json
import asyncio
import websockets
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from twilio.rest import Client

from utils import (
    get_fargate_public_ip, get_signed_url, get_agent_system_prompt
)
from config import (
    logger,
    TWILIO_PHONE_NUMBER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
    TARGET_PHONE, VOICE_CALL_ID,
)
from database_service import get_db_connection, log_message


MAX_CALL_DURATION_SECONDS = 30 * 60

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

async def startup_event():
    try:
        logger.info("=== STARTUP EVENT STARTED ===")
        logger.info("Fargate task started. Initiating call...")
        asyncio.create_task(shutdown_timer(MAX_CALL_DURATION_SECONDS))

        logger.info("Creating task for call initiation...")
        asyncio.create_task(initiate_call_on_startup())
        logger.info("=== STARTUP EVENT COMPLETED ===")
    except Exception as e:
        logger.error(f"Error in startup event: {e}")
        import traceback
        traceback.print_exc()
        raise

# --- Timer task ---
async def shutdown_timer(duration: int):
    """Countdown and exit application after a certain duration."""
    logger.info(f"Application self-destruct timer started for {duration} seconds.")
    await asyncio.sleep(duration)
    logger.info(f"Maximum call duration of {duration} seconds reached. Shutting down task.")
    # Use sys.exit() to exit the process cleanly.
    # Uvicorn and Fargate will recognize that the process has ended.
    sys.exit(0)

async def initiate_call_on_startup():
    logger.info("Initiating call...")
    
    # 1. Read state from environment variables
    if not TARGET_PHONE or not VOICE_CALL_ID:
        logger.error("TARGET_PHONE or VOICE_CALL_ID environment variables not set. Exiting.")
        # Exit application to stop Fargate task
        # os._exit(1) 
        return # Better to return to avoid crash loop

    # 2. Discover public IP
    public_ip = get_fargate_public_ip()
    if not public_ip:
        logger.error("Failed to get public IP. Cannot make the call. Exiting.")
        sys.exit(1)

    # 3. Build WebSocket URL and TwiML
    websocket_url = f"wss://{public_ip}/media-stream/{TARGET_PHONE}/{VOICE_CALL_ID}"
    target_phone_with_plus = TARGET_PHONE if TARGET_PHONE.startswith("+") else "+" + TARGET_PHONE
    outbound_twiml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response>'
        f'  <Connect>'
        f'    <Stream url="{websocket_url}" />'
        f'  </Connect>'
        f'</Response>'
    )
    logger.info(f"Outbound TwiML: {outbound_twiml}")
    logger.info(f"Constructed WebSocket URL: {websocket_url}")
    
    # 4. Call Twilio
    try:
        target_phone_with_plus = TARGET_PHONE if TARGET_PHONE.startswith("+") else "+" + TARGET_PHONE
        call = client.calls.create(
            record=False,
            from_=TWILIO_PHONE_NUMBER,
            to=target_phone_with_plus,
            twiml=outbound_twiml,
        )
        logger.info(f"Call SID: {call.sid}")
        logger.info(f"Successfully initiated call to {target_phone_with_plus}")
    except Exception as e:
        logger.error(f"Failed to create Twilio call: {e}")
        # os._exit(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start timer task when application starts."""
    logger.info("Starting application...")
    try:
        await startup_event()
        yield
    except Exception as e:
        logger.error(f"Application error: {e}")
    finally:
        logger.info("Shutting down application...")

app = FastAPI(lifespan=lifespan)

@app.websocket("/media-stream/{target_phone}/{voice_call_id}")
async def outbound_media_stream(websocket: WebSocket, target_phone: str, voice_call_id: int):
    logger.info("[Server] Client connected to outbound media stream")
    await websocket.accept()
    logger.info("[Server] Twilio connected to outbound media stream")

    # context = await get_conversation_context(voice_call_id)
    context = ""

    # Override the conversation config
    system_prompt = await get_agent_system_prompt()
    override_prompt = f"{system_prompt}\n\nContext:\n{context}"
    conversation_config_override = {
        "agent": {
            "prompt": {
                "prompt": override_prompt
            }
        }
    }

    # Variables to track the call
    stream_sid = None
    call_sid = None
    elevenlabs_ws = None
    custom_parameters = None
    conversation_ended = False
    
    try:
        # Connect to DB
        db_conn = get_db_connection()

        # Set up ElevenLabs connection
        signed_url = await get_signed_url()
        logger.info(f"[ElevenLabs] Signed URL: {signed_url}")
        
        async with websockets.connect(signed_url) as elevenlabs_ws:
            logger.info("[ElevenLabs] Connected to Conversational AI")
            
            # Send the conversation config override to ElevenLabs
            await elevenlabs_ws.send(json.dumps(conversation_config_override))
            logger.info(f"[ElevenLabs] Sent conversation config override: {conversation_config_override}")
            
            # Process messages from Twilio
            # Forward Twilio audio chunks to ElevenLabs
            async def process_twilio_messages():
                nonlocal stream_sid, call_sid, custom_parameters, conversation_ended
                
                try:
                    async for message in websocket.iter_text():
                        msg = json.loads(message)
                        
                        if msg["event"] != "media":
                            logger.info(f"[Twilio] Received event: {msg['event']}")
                    
                        if msg["event"] == "start":
                            stream_sid = msg["start"]["streamSid"]
                            call_sid = msg["start"]["callSid"]
                            custom_parameters = msg["start"].get("customParameters", {})
                            logger.info(f"[Twilio] Stream started - StreamSid: {stream_sid}, CallSid: {call_sid}")
                            logger.info(f"[Twilio] Start parameters: {custom_parameters}")
                            
                        elif msg["event"] == "media":
                            if elevenlabs_ws:
                                audio_message = {
                                    "user_audio_chunk": msg["media"]["payload"]
                                }
                                await elevenlabs_ws.send(json.dumps(audio_message))
                                
                        elif msg["event"] == "stop":
                            logger.info(f"[Twilio] Stream {stream_sid} ended")
                            conversation_ended = True
                            handle_postcall(target_phone)
                            sys.exit(0)
                        
                except Exception as e:
                    logger.error(f"[Twilio] Error processing message: {e}")
            
            # Process responses from ElevenLabs
            async def process_elevenlabs_messages():
                nonlocal conversation_ended

                while not conversation_ended:
                    try:
                        data = await elevenlabs_ws.recv()
                        message = json.loads(data)
                        
                        message_type = message.get("type")
                        
                        if message_type == "conversation_initiation_metadata":
                            # TODO: Update ElevenLabs conversation ID in the database
                            pass

                        elif message_type == "audio":
                            # If response is audio chunks, forward them back to Twilio
                            if stream_sid:
                                audio_chunk = None
                                if "audio" in message and "chunk" in message["audio"]:
                                    audio_chunk = message["audio"]["chunk"]
                                elif "audio_event" in message and "audio_base_64" in message["audio_event"]:
                                    audio_chunk = message["audio_event"]["audio_base_64"]
                                
                                if audio_chunk:
                                    audio_data = {
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {
                                            "payload": audio_chunk
                                        }
                                    }
                                    await websocket.send_text(json.dumps(audio_data))
                            else:
                                logger.info("[ElevenLabs] Received audio but no StreamSid yet")
                                
                        elif message_type == "interruption":
                            if stream_sid:
                                await websocket.send_text(json.dumps({
                                    "event": "clear",
                                    "streamSid": stream_sid
                                }))
                                
                        elif message_type == "ping":
                            if "ping_event" in message and "event_id" in message["ping_event"]:
                                await elevenlabs_ws.send(json.dumps({
                                    "type": "pong",
                                    "event_id": message["ping_event"]["event_id"]
                                }))
                                
                        elif message_type == "agent_response":
                            if "agent_response_event" in message and "agent_response" in message["agent_response_event"]:
                                content = message["agent_response_event"]["agent_response"]
                                logger.info(f"[Twilio] Agent response: {content}")
                                await save_message_to_db(
                                    db_conn,
                                    target_phone,
                                    "ai",
                                    content,
                                )
                                
                        elif message_type == "user_transcript":
                            if "user_transcription_event" in message and "user_transcript" in message["user_transcription_event"]:
                                content = message["user_transcription_event"]["user_transcript"]
                                logger.info(f"[Twilio] User transcript: {content}")
                                await save_message_to_db(
                                    db_conn,
                                    target_phone,
                                    "user",
                                    content,
                                )
                            
                    except Exception as e:
                        logger.error(f"[ElevenLabs] Error processing message: {e}")
                        break
            
            # Run both tasks concurrently
            await asyncio.gather(
                process_twilio_messages(),
                process_elevenlabs_messages()
            )
            
    except Exception as e:
        logger.error(f"[Server] WebSocket error: {e}")
    
    finally:
        logger.info("[Twilio] Client disconnected")

def handle_postcall(db_conn, target_phone: str):
    """
    Handle postcall for a voice call.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("""
            UPDATE voice_calls
            SET status = 'completed'
            WHERE target_phone = %s
            RETURNING *
        """, (target_phone,))
        voice_call = cursor.fetchone()
        if voice_call:
            logger.info(f"[Twilio] Updated voice call status to COMPLETED")
        else:
            logger.error(f"[Twilio] Voice call not found for phone number: {target_phone}")
        
        # Summarize the conversation
        # TODO: Summarize the conversation

async def save_message_to_db(db_conn, whatsapp_id, sender, content):
    def _save_message():
        with db_conn.cursor() as cursor:
            log_message(cursor, whatsapp_id, sender, content)
    return await asyncio.to_thread(_save_message)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
