import os
import json
import asyncio
import websockets

from fastapi import FastAPI, WebSocket
from dotenv import load_dotenv
from psycopg2.extensions import cursor as Psycopg2Cursor

import openai_service as ai
import database_service as db
import wati_service as wati
from utils import get_signed_url, get_agent_id_by_language, get_system_prompt
from config import (
    logger, ELEVENLABS_API_KEY
)
from database_service import log_message

load_dotenv()

MAX_CALL_DURATION_SECONDS = int(os.environ.get("MAX_CALL_DURATION_SECONDS", 1800))
logger.info(f"[Server] Max call duration: {MAX_CALL_DURATION_SECONDS} seconds")

app = FastAPI()

@app.websocket("/media-stream/{target_phone}/{voice_call_id}/{voice_language}")
async def outbound_media_stream(websocket: WebSocket, target_phone: str, voice_call_id: int, voice_language: str):
    logger.info("[Server] Client connected to outbound media stream")
    await websocket.accept()
    logger.info("[Server] Twilio connected to outbound media stream")

    context = ""

    # Override the conversation config
    system_prompt = get_system_prompt(voice_language)
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
        db_conn = db.get_db_connection()

        # Set up ElevenLabs connection
        logger.info(f"[ElevenLabs] Voice language: {voice_language}")
        signed_url = await get_signed_url(
            api_key=ELEVENLABS_API_KEY,
            agent_id=get_agent_id_by_language(voice_language)
        )
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
                            handle_postcall(db_conn, voice_call_id, call_sid, stream_sid, target_phone)
                            break
                        
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
                                asyncio.create_task(log_message(
                                    db_conn,
                                    target_phone,
                                    "ai",
                                    content,
                                ))
                                
                        elif message_type == "user_transcript":
                            if "user_transcription_event" in message and "user_transcript" in message["user_transcription_event"]:
                                content = message["user_transcription_event"]["user_transcript"]
                                logger.info(f"[Twilio] User transcript: {content}")
                                asyncio.create_task(log_message(
                                    db_conn,
                                    target_phone,
                                    "user",
                                    content,
                                ))
                            
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

def handle_postcall(db_conn: Psycopg2Cursor, voice_call_id: int, call_sid: str, stream_sid: str, target_phone: str):
    """
    Handle postcall for a voice call.

    Args:
        db_conn: The database connection
        target_phone: The target phone number (user's WhatsApp phone number)
    """
    with db_conn.cursor() as cursor:
        cursor.execute("""
            UPDATE voice_calls
            SET status = 'completed',
                call_sid = %s,
                stream_sid = %s
            WHERE id = %s AND target_phone = %s
            RETURNING *
        """, (call_sid, stream_sid, voice_call_id, target_phone))
        voice_call = cursor.fetchone()
        if voice_call:
            logger.info(f"[Twilio] Updated voice call status to COMPLETED")
        else:
            logger.error(f"[Twilio] Voice call not found for phone number: {target_phone}")
        
        # Call OpenAI API to get response
        call_history = db.get_call_history(cursor, target_phone)
        logger.debug(f"[Twilio] Call history: {call_history[:30]}")

        system_prompt = ai.construct_openai_prompt(call_history)
        response = ai.call_openai_api(system_prompt)
        logger.info(f"[OpenAI] AI has replied to the user")

        # If coaching session is completed, increase the number of coaching sessions
        if response.get("coaching_session_completed", False):
            cursor.execute("""
                UPDATE parents
                SET session_count = session_count + 1
                WHERE whatsapp_id = %s
            """, (target_phone,))
            logger.info(f"[Database] Increased coaching sessions for user: {target_phone}")
        
        
        # Send response to WhatsApp
        wati.send_text_message(target_phone, response["reply_to_user"])
        logger.info(f"[WhatsApp] Sent response to the user")

        asyncio.create_task(log_message(
            db_conn,
            target_phone,
            "ai",
            response["reply_to_user"],
            "whatsapp",
        ))
        logger.info(f"[Database] Logged response to the user")

        # Activate the trial plan if user's subscription status = 'pre_trial'
        cursor.execute("""
            UPDATE parents
            SET subscription_status = 'trialing'
            WHERE whatsapp_id = %s AND subscription_status = 'pre_trial'
        """, (target_phone,))
        db_conn.commit()
        logger.info(f"[Database] Activated trial plan for user: {target_phone}")


async def log_message(db_conn: Psycopg2Cursor, whatsapp_id: str, sender: str, content: str, message_type: str = "call"):
    """
    Log a message to the database.

    Args:
        db_conn: The database connection
        whatsapp_id: The WhatsApp ID of the user
        sender: The sender of the message ('user' or 'ai')
        content: The content of the message
    """
    def _log_message():
        with db_conn.cursor() as cursor:
            logger.info(f"[Database] Logging message: {whatsapp_id}, {sender}, {content[:20]}...")
            cursor.execute("""
                INSERT INTO messages (parent_id, sender, content, message_type)
                SELECT id, %s, %s, %s
                FROM parents 
                WHERE whatsapp_id = %s
                RETURNING id
            """, (sender, content, message_type, whatsapp_id))
            db_conn.commit()
            logger.info(f"[Database] Logged message: {whatsapp_id}, {sender}, {content[:20]}...")
    return await asyncio.to_thread(_log_message)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
