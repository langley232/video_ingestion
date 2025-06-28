# audio_api/backend/main.py (Corrected)

import requests
from fastapi import FastAPI, HTTPException
# CORRECTED: Added StreamingResponse import
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import os
import io
# CORRECTED: Added datetime import
from datetime import datetime

app = FastAPI(title="Audio API Backend", version="1.0.0")

# Google Cloud TTS Configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable not set.")


class TextToSpeechRequest(BaseModel):
    text: str
    language_code: str = Field(
        "en-US", description="Language code for the speech synthesis.")
    voice_name: str = Field(
        "en-US-Studio-M", description="Voice name for the speech synthesis.")
    speaking_rate: float = Field(
        1.0, ge=0.25, le=4.0, description="Speaking rate (0.25 to 4.0).")
    pitch: float = Field(0.0, ge=-20.0, le=20.0,
                         description="Speaking pitch (-20.0 to 20.0).")


@app.post("/synthesize/")
async def synthesize_speech(request: TextToSpeechRequest):
    try:
        # Use Google Cloud TTS REST API with API key
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_API_KEY}"

        payload = {
            "input": {
                "text": request.text
            },
            "voice": {
                "languageCode": request.language_code,
                "name": request.voice_name
            },
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": request.speaking_rate,
                "pitch": request.pitch
            }
        }

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        # Decode base64 audio content
        import base64
        audio_content = base64.b64decode(response.json()["audioContent"])

        # Wrap audio bytes in BytesIO object
        audio_stream = io.BytesIO(audio_content)

        return StreamingResponse(audio_stream, media_type="audio/mpeg")

    except requests.exceptions.Timeout:
        error_msg = "Google TTS API request timed out"
        raise HTTPException(status_code=503, detail=error_msg)
    except requests.exceptions.RequestException as e:
        error_msg = f"Google TTS API request failed: {str(e)}"
        raise HTTPException(status_code=500, detail=error_msg)
    except Exception as e:
        error_msg = f"Speech synthesis failed: {str(e)}"
        raise HTTPException(status_code=500, detail=error_msg)

# Endpoint to list available voices
@app.get("/voices/")
async def list_voices():
    try:
        url = f"https://texttospeech.googleapis.com/v1/voices?key={GOOGLE_API_KEY}"
        response = requests.get(url)
        response.raise_for_status()

        voices_data = response.json()
        return [{"voice_id": voice["name"], "name": voice["name"]} for voice in voices_data.get("voices", [])]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve voices: {str(e)}")

# Health check endpoint
@app.get("/health/")
async def health_check():
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "audio_api_backend",
        "components": {},
        "errors": []
    }

    try:
        # Test Google TTS API connection
        try:
            url = f"https://texttospeech.googleapis.com/v1/voices?key={GOOGLE_API_KEY}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            health_status["components"]["google_tts"] = "connected"
        except requests.exceptions.Timeout:
            error_msg = "Google TTS API timeout after 10s"
            health_status["components"]["google_tts"] = "timeout"
            health_status["errors"].append(error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = f"Google TTS API error: {str(e)}"
            health_status["components"]["google_tts"] = "api_error"
            health_status["errors"].append(error_msg)
        except Exception as e:
            error_msg = f"Google TTS API unexpected error: {str(e)}"
            health_status["components"]["google_tts"] = "error"
            health_status["errors"].append(error_msg)

        # Determine overall status
        if health_status["errors"]:
            health_status["status"] = "unhealthy"
        else:
            health_status["status"] = "healthy"

        return health_status

    except Exception as e:
        error_msg = f"Health check failed: {str(e)}"
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "service": "audio_api_backend",
            "error": error_msg,
            "troubleshooting": "Run 'docker-compose logs audio_api_backend' for detailed error information"
        }
