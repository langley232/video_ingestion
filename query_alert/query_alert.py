# file identifier: query_alert/query_alert.py
from fastapi import FastAPI
import os
import time
import cv2
import tempfile
import json
import requests
from minio import Minio
from minio.error import S3Error
import logging
import numpy as np
import base64
from kafka import KafkaConsumer
import threading
import io

app = FastAPI()

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
TOPIC_NAME = "video-ingestion"
CONSUMER_GROUP = "query-alert-group"

# Initialize Kafka Consumer
consumer = KafkaConsumer(
    TOPIC_NAME,
    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id=CONSUMER_GROUP,
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

# Initialize MinIO client
minio_client = Minio(
    os.getenv("MINIO_ENDPOINT", "minio:9000"),
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
    secure=False
)
bucket_name = os.getenv("MINIO_BUCKET", "videos")

try:
    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)
        logger.info(f"Created MinIO bucket: {bucket_name}")
except S3Error as e:
    logger.error(f"Error creating MinIO bucket: {str(e)}")
    raise

ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
vision_model_name = "moondream:1.8b"  # Changed from llava_model
summary_model = "nomic-embed-text:latest"

storage_endpoint = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")
AUDIO_BACKEND_ENDPOINT = os.getenv(
    "AUDIO_BACKEND_ENDPOINT", "http://audio_backend:8000")

# Configuration for object detection
DETECTION_CONFIG = {
    "target_objects": [
        "drone",
        "military drone",
        "unmanned aerial vehicle",
        "UAV",
        "quadcopter",
        "aircraft",
        "flying object"
    ],
    "confidence_threshold": 0.6,  # Lowered threshold for better detection
    "model": "moondream:1.8b"
}


def extract_frame(video_data):
    with tempfile.NamedTemporaryFile(suffix=".mp4") as temp_file:
        temp_file.write(video_data)
        temp_file.flush()
        cap = cv2.VideoCapture(temp_file.name)
        ret, frame = cap.read()
        cap.release()
        if ret:
            _, buffer = cv2.imencode('.jpg', frame)
            return buffer.tobytes()
        return None


def analyze_frame(frame_data: bytes) -> dict:
    try:
        img_base64 = base64.b64encode(frame_data).decode("utf-8")
        payload = {
            "model": DETECTION_CONFIG["model"],
            "prompt": "Analyze this image for any aerial vehicles, drones, or suspicious flying objects. Focus on military or surveillance drones. Return a JSON with detected objects, their type, and confidence scores. Include any relevant details about the object's appearance or behavior.",
            "images": [img_base64],
            "format": "json"
        }
        response = requests.post(
            f"{ollama_endpoint}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        result = json.loads(response.text.split('\n')[-2])['response']
        return json.loads(result)
    except Exception as e:
        logger.error(f"Error analyzing frame: {str(e)}")
        return {"objects": [], "error": str(e)}


def query_similar_videos(embedding: list) -> list:
    try:
        payload = {"embedding": embedding}
        response = requests.post(
            f"{storage_endpoint}/search", json=payload, timeout=10)
        response.raise_for_status()
        return response.json().get("similar_videos", [])
    except Exception as e:
        logger.error(f"Error querying similar videos: {str(e)}")
        return []


def summarize_sightings(sightings: list) -> str:
    try:
        prompt = f"Summarize the following sightings of objects (drones or people resembling Tom Cruise) with their timestamps and locations:\n{json.dumps(sightings, indent=2)}\nProvide a concise summary in natural language."
        payload = {
            "model": summary_model,
            "prompt": prompt
        }
        response = requests.post(
            f"{ollama_endpoint}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        result = json.loads(response.text.split('\n')[-2])['response']
        return result
    except Exception as e:
        logger.error(f"Error summarizing sightings: {str(e)}")
        return "Failed to summarize sightings."


def store_alert(video_path: str, objects: list, similar_videos: list, metadata: dict, summary: str):
    try:
        # Generate alert text for speech synthesis
        alert_text = f"ALERT: {summary}"
        if metadata.get("sightings"):
            for sighting in metadata["sightings"]:
                alert_text += f" Detected {sighting['object']} with {sighting['confidence']:.0%} confidence. "
                if sighting.get("details"):
                    alert_text += f"Details: {sighting['details']}. "

        # Attempt text-to-speech synthesis
        try:
            logger.info(f"Generating speech alert: {alert_text[:100]}...")
            tts_payload = {
                "text": alert_text,
                "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel voice
                "model_id": "eleven_turbo_v2_5",
                "stability": 0.5,
                "similarity_boost": 0.75
            }
            response = requests.post(
                f"{AUDIO_BACKEND_ENDPOINT}/synthesize/", json=tts_payload, timeout=20)

            if response.status_code == 200:
                # Store the audio alert
                audio_path = f"alerts/audio/alert_{int(time.time())}.mp3"
                minio_client.put_object(
                    bucket_name, audio_path,
                    io.BytesIO(response.content),
                    len(response.content),
                    content_type="audio/mpeg"
                )
                logger.info(f"Stored audio alert: {audio_path}")
            else:
                logger.error(
                    f"Speech synthesis failed with status {response.status_code}")
        except Exception as e:
            logger.error(f"Error generating speech alert: {str(e)}")

        # Store alert data
        alert_data = {
            "video_path": video_path,
            "objects": objects,
            "similar_videos": similar_videos,
            "metadata": metadata,
            "summary": summary,
            "alert_text": alert_text,
            "audio_path": audio_path if 'audio_path' in locals() else None,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        # Store individual alert
        alert_path = f"alerts/alert_{int(time.time())}.json"
        with open("/tmp/alert.json", "w") as f:
            json.dump(alert_data, f)
        minio_client.fput_object(bucket_name, alert_path, "/tmp/alert.json")

        # Update latest sightings
        minio_client.fput_object(
            bucket_name, "alerts/latest_sightings.json", "/tmp/alert.json")

        logger.info(f"Stored alert: {alert_path}")
        return alert_data
    except Exception as e:
        logger.error(f"Error storing alert: {str(e)}")
        return None


def process_video(video_path: str, timestamp: str):
    try:
        logger.info(f"Processing video: {video_path}")

        # Get video metadata
        metadata_path = video_path.replace(
            "generated_videos/", "metadata/").replace(".mp4", ".json")
        try:
            metadata_response = minio_client.get_object(
                bucket_name, metadata_path)
            video_metadata = json.loads(metadata_response.read().decode())
            metadata_response.close()
            metadata_response.release_conn()
        except S3Error:
            logger.warning(f"No metadata found for {video_path}")
            video_metadata = {}

        # Get video content
        response = minio_client.get_object(bucket_name, video_path)
        video_data = response.read()
        response.close()
        response.release_conn()

        frame_data = extract_frame(video_data)
        if not frame_data:
            logger.warning(f"Failed to extract frame from {video_path}")
            return

        analysis = analyze_frame(frame_data)
        objects_detected = analysis.get("objects", [])

        # Check for suspicious objects
        suspicious = [
            obj for obj in objects_detected
            if any(target.lower() in obj["name"].lower() for target in DETECTION_CONFIG["target_objects"])
            and obj["confidence"] > DETECTION_CONFIG["confidence_threshold"]
        ]

        if suspicious:
            # Use location from metadata if available
            location = video_metadata.get("location", {
                "latitude": 40.7829,
                "longitude": -73.9654,
                "name": "Central Park"
            })

            # Create detailed description
            detection_details = []
            for obj in suspicious:
                details = f"{obj['name']} (confidence: {obj['confidence']:.2f})"
                if 'details' in obj:
                    details += f" - {obj['details']}"
                detection_details.append(details)

            detection_text = " | ".join(detection_details)
            logger.info(f"Detected objects: {detection_text}")

            # Get embeddings for similarity search
            embedding_response = requests.post(
                f"{ollama_endpoint}/api/embeddings",
                json={
                    "model": "nomic-embed-text:latest",
                    "prompt": f"Video showing: {detection_text}"
                },
                timeout=20
            )
            embedding_response.raise_for_status()
            embedding = embedding_response.json().get("embedding", [])

            similar_videos = query_similar_videos(embedding)

            # Create sightings with enhanced metadata
            sightings = []
            for obj in suspicious:
                sighting = {
                    "object": obj["name"],
                    "confidence": obj["confidence"],
                    "details": obj.get("details", ""),
                    "video_path": video_path,
                    "timestamp": timestamp,
                    "location": location,
                    "video_metadata": video_metadata.get("video_metadata", {})
                }
                sightings.append(sighting)

            if sightings:
                summary = summarize_sightings(sightings)
                alert_data = store_alert(video_path, suspicious, similar_videos, {
                    "sightings": sightings,
                    "location": location,
                    "video_metadata": video_metadata
                }, summary)

    except Exception as e:
        logger.error(f"Error processing video {video_path}: {str(e)}")


def kafka_consumer_loop():
    """Main loop for consuming Kafka messages"""
    logger.info("Starting Kafka consumer loop...")
    try:
        for message in consumer:
            try:
                data = message.value
                logger.info(f"Received message: {data}")

                video_path = data.get('video_path')
                timestamp = data.get('timestamp')

                if video_path and timestamp:
                    process_video(video_path, timestamp)
                else:
                    logger.warning(
                        "Missing video_path or timestamp in message")

            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                continue
    except Exception as e:
        logger.error(f"Error in Kafka consumer loop: {str(e)}")
        # Attempt to reconnect
        time.sleep(5)
        kafka_consumer_loop()


# Start Kafka consumer in a separate thread
consumer_thread = threading.Thread(target=kafka_consumer_loop, daemon=True)
consumer_thread.start()


@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
