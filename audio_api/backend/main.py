from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import os
import io
from fastapi.responses import StreamingResponse

# Import the correct client for v1.8+
from elevenlabs.client import ElevenLabs

app = FastAPI()

# Get your Eleven Labs API key from environment variables
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

if not ELEVENLABS_API_KEY:
    raise ValueError("ELEVENLABS_API_KEY environment variable not set.")

# Initialize the ElevenLabs client
client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

class TextToSpeechRequest(BaseModel):
    text: str
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Default voice ID (Rachel)
    model_id: str = "eleven_turbo_v2_5"  # Added model_id with a default
    stability: float = Field(0.5, ge=0.0, le=1.0)  # Added stability with validation
    similarity_boost: float = Field(0.75, ge=0.0, le=1.0)  # Added similarity_boost with validation

@app.post("/synthesize/")
async def synthesize_speech(request: TextToSpeechRequest):
    try:
        # Use the correct method for text-to-speech generation
        audio = client.text_to_speech.convert(
            voice_id=request.voice_id,
            text=request.text,
            model_id=request.model_id,
            voice_settings={
                "stability": request.stability,
                "similarity_boost": request.similarity_boost
            }
        )

        # Convert audio generator/iterator to bytes
        if hasattr(audio, '__iter__') and not isinstance(audio, (bytes, bytearray)):
            audio_bytes = b''.join(audio)
        else:
            audio_bytes = audio

        # Wrap audio bytes in BytesIO object
        audio_stream = io.BytesIO(audio_bytes)

        return StreamingResponse(audio_stream, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Speech synthesis failed: {str(e)}")

# Endpoint to list available voices
@app.get("/voices/")
async def list_voices():
    try:
        # Get all voices using the correct client method
        voices_response = client.voices.get_all()
        return [{"voice_id": voice.voice_id, "name": voice.name} for voice in voices_response.voices]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve voices: {str(e)}")

# Health check endpoint
@app.get("/health/")
async def health_check():
    return {"status": "healthy", "service": "audio_api_backend"}
