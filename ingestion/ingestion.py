from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from confluent_kafka import Producer
import logging
import cv2
import numpy as np
import requests
import json
import os
from datetime import datetime
import asyncio
import websockets

app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
producer_config = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
    "client.id": "ingestion-producer"
}
producer = Producer(producer_config)

# WebSocket configuration for real-time alerts
ALERT_WS_URL = "ws://streamlit:8501/alert"

def delivery_report(err, msg):
    """Callback for Kafka message delivery."""
    if err is not None:
        logger.error(f"Message delivery failed: {err}")
    else:
        logger.info(f"Message delivered to {msg.topic()} [{msg.partition()}]")

def detect_objects(frame):
    """Detect objects in a frame using MiniCPM-V 2.6 via Ollama."""
    try:
        _, buffer = cv2.imencode('.jpg', frame)
        response = requests.post(
            'http://ollama:11434/api/generate',
            json={
                'model': 'minicpm-v:2.6',
                'prompt': 'Detect objects in this image (e.g., tank, military vehicle, missile, drone, person).',
                'image': buffer.tobytes().hex()
            }
        )
        response.raise_for_status()
        objects = response.json().get('objects', [])
        return objects if objects else []
    except Exception as e:
        logger.error(f"Error detecting objects: {str(e)}")
        return []

async def send_realtime_alert(video_content, timestamp, objects):
    """Send real-time alert to Streamlit via WebSocket."""
    if any(obj.lower() in ['drone', 'missile', 'enemy flying object'] for obj in objects):
        alert_data = {
            "video_content": video_content.hex(),
            "timestamp": timestamp,
            "objects": objects,
            "geolocation": "White House, 1600 Pennsylvania Ave NW, Washington, DC 20500"
        }
        async with websockets.connect(ALERT_WS_URL) as websocket:
            await websocket.send(json.dumps(alert_data))
            logger.info(f"Sent alert for {objects} at {timestamp}")

@app.post("/ingest")
async def ingest_video(file: UploadFile = File(...), timestamp: str = Form(None)):
    """Ingest a video file and send it to Kafka with real-time alerts."""
    try:
        # Read video file
        video_bytes = await file.read()
        video_array = np.frombuffer(video_bytes, dtype=np.uint8)
        video = cv2.imdecode(video_array, cv2.IMREAD_COLOR)

        if video is None:
            raise HTTPException(status_code=400, detail="Invalid video file")

        # Detect objects
        objects = detect_objects(video)

        # Prepare metadata
        if timestamp:
            try:
                datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid timestamp format. Use YYYY-MM-DD HH:MM:SS")
        else:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        metadata = {
            "video_content": video_bytes.hex(),
            "timestamp": timestamp,
            "objects": objects
        }

        # Send to Kafka
        producer.produce(
            topic="video-ingestion",
            value=json.dumps(metadata).encode('utf-8'),
            callback=delivery_report
        )
        producer.flush()

        # Send real-time alert if applicable
        await send_realtime_alert(video_bytes, timestamp, objects)

        return {"status": "Video ingested", "objects": objects}

    except Exception as e:
        logger.error(f"Error ingesting video: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
