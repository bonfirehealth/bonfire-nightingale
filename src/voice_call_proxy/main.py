import os
import json
import asyncio
import websockets
import sys

from fastapi import FastAPI, WebSocket
from dotenv import load_dotenv

from utils import (
    get_signed_url
)
from config import logger, SYSTEM_PROMPT
from database_service import log_message

load_dotenv()

MAX_CALL_DURATION_SECONDS = int(os.environ.get("MAX_CALL_DURATION_SECONDS", 1800))

app = FastAPI()

@app.websocket("/media-stream/{target_phone}/{voice_call_id}")
async def outbound_media_stream(websocket: WebSocket, target_phone: str, voice_call_id: int):
    logger.info("[Server] Client connected to outbound media stream")
    await websocket.accept()
    logger.info("[Server] Twilio connected to outbound media stream")

    # context = await get_conversation_context(voice_call_id)
    context = ""

    # Override the conversation config
    # system_prompt = await get_agent_system_prompt()
    override_prompt = f"{SYSTEM_PROMPT}\n\nContext:\n{context}"
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
        # db_conn = get_db_connection()

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
                            # handle_postcall(target_phone)
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
                                # await save_message_to_db(
                                #     db_conn,
                                #     target_phone,
                                #     "ai",
                                #     content,
                                # )
                                
                        elif message_type == "user_transcript":
                            if "user_transcription_event" in message and "user_transcript" in message["user_transcription_event"]:
                                content = message["user_transcription_event"]["user_transcript"]
                                logger.info(f"[Twilio] User transcript: {content}")
                                # await save_message_to_db(
                                #     db_conn,
                                #     target_phone,
                                #     "user",
                                #     content,
                                # )
                            
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
