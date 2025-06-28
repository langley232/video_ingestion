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
from confluent_kafka import Consumer, KafkaError
import threading
import io
import re # Added for robust JSON parsing

app = FastAPI()

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
TOPIC_NAME = "video-ingestion"
CONSUMER_GROUP = "query-alert-group"

# Initialize Kafka Consumer (Using confluent_kafka.Consumer)
consumer_config = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
    "group.id": CONSUMER_GROUP,
    "auto.offset.reset": "earliest",
    "enable.auto.commit": "true"
}
consumer = Consumer(consumer_config)

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

# Correct endpoints for the split Ollama services
OLLAMA_VISION_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama_vision:11434") # For Qwen2.5-VL
OLLAMA_EMBEDDINGS_ENDPOINT = os.getenv("OLLAMA_EMBEDDINGS_ENDPOINT", "http://ollama_embeddings:11434") # For Nomic-embed-text

vision_model_name = "qwen2.5vl:3b"
summary_model = "nomic-embed-text:latest"

storage_endpoint = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")
AUDIO_BACKEND_ENDPOINT = os.getenv(
    "AUDIO_BACKEND_ENDPOINT", "http://audio_backend:8002")


# Configuration for object detection
DETECTION_CONFIG = {
    "target_objects": [
        "drone",
        "military drone",
        "unmanned aerial vehicle",
        "UAV",
        "quadcopter",
        "fixed-wing drone",
        "rotorcraft",
        "aircraft",
        "flying object",
        "airplane",
        "helicopter"
    ],
    "confidence_threshold": 0.3, # Lowered for better initial detection
    "model": "qwen2.5vl:3b"
}


def trigger_alert_workflow(video_path: str, timestamp: str, location: dict, suspicious_objects: list):
    """
    Triggers the full alert workflow for detected suspicious objects.
    """
    try:
        logger.info(f"Triggering alert workflow for {video_path} based on detected suspicious objects.")

        # 1. Generate embedding for the detected objects to find similar past events
        # We create a text description of the event for the embedding model
        detection_details = [f"{obj['object_type']} (confidence: {obj['confidence']:.2f})" for obj in suspicious_objects]
        detection_text = " | ".join(detection_details)
        
        embedding = None
        try:
            embedding_response = requests.post(
                f"{OLLAMA_EMBEDDINGS_ENDPOINT}/api/embeddings",
                json={
                    "model": "nomic-embed-text:latest",
                    "prompt": f"Alert for detected objects: {detection_text} near {location.get('name', 'unknown')}"
                },
                timeout=30
            )
            embedding_response.raise_for_status()
            embedding = embedding_response.json().get("embedding", [])
            logger.info("Generated embedding for similarity search.")
        except Exception as e:
            logger.error(f"Error generating embedding for suspicious object: {e}")
            # Continue without similarity search if embedding fails

        # 2. Query for similar videos
        similar_videos = []
        if embedding:
            similar_videos = query_similar_videos(embedding)
            logger.info(f"Found {len(similar_videos)} similar videos.")

        # 3. Format sightings for summarization
        sightings = []
        for obj in suspicious_objects:
            sighting = {
                "object": obj["object_type"],
                "confidence": obj["confidence"],
                "details": f"Detected in frame {obj.get('frame_number', 'N/A')}",
                "video_path": video_path,
                "timestamp": timestamp,
                "location": location
            }
            sightings.append(sighting)

        # 4. Generate an intelligent summary
        summary = summarize_sightings(sightings)
        logger.info(f"Generated summary: {summary}")

        # 5. Store the comprehensive alert
        alert_data = store_alert(video_path, suspicious_objects, similar_videos, {"timestamp": timestamp, "location": location, "sightings": sightings}, summary)
        logger.info(f"Successfully generated and stored alert for {video_path}: {alert_data.get('alert_path')}")

    except Exception as e:
        logger.error(f"Error in alert workflow for {video_path}: {e}")


def kafka_consumer_loop():
    """Main loop for consuming Kafka messages and processing videos."""
    logger.info("Starting Kafka consumer loop for query_alert...")
    max_retries = 10
    retry_delay = 10

    for attempt in range(max_retries):
        try:
            consumer.subscribe([TOPIC_NAME])
            logger.info(f"Successfully subscribed to {TOPIC_NAME}")
            break
        except Exception as e:
            logger.error(f"Kafka subscription failed (Attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error(f"Max retries reached for Kafka subscription. Consumer might not receive messages.")
                return # Exit if subscription fails

    try:
        while True:
            msg = consumer.poll(1.0) # Poll for messages (timeout in seconds)

            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    logger.error(f"Kafka consumer error: {msg.error()}")
                    break

            try:
                data = json.loads(msg.value().decode("utf-8"))
                logger.info(f"Received message from Kafka: {data.get('video_path')}")

                # Check for the new suspicious objects key
                suspicious_objects = data.get('suspicious_objects_found')
                
                if suspicious_objects and isinstance(suspicious_objects, list) and len(suspicious_objects) > 0:
                    logger.info(f"Found {len(suspicious_objects)} suspicious objects in message for {data.get('video_path')}. Triggering alert.")
                    # Trigger the alert workflow with the data from the message
                    trigger_alert_workflow(
                        video_path=data.get('video_path'),
                        timestamp=data.get('timestamp'),
                        location=data.get('location'),
                        suspicious_objects=suspicious_objects
                    )
                else:
                    logger.info(f"No suspicious objects found in message for {data.get('video_path')}. No action needed.")

            except json.JSONDecodeError as e:
                logger.error(f"Error decoding Kafka message JSON: {e}")
            except Exception as e:
                logger.error(f"Error processing Kafka message: {e}")

    except KeyboardInterrupt:
        logger.info("Shutting down query_alert consumer...")
    finally:
        logger.info("Closing Kafka consumer for query_alert...")
        consumer.close()


# Start Kafka consumer in a separate thread
consumer_thread = threading.Thread(target=kafka_consumer_loop, daemon=True)
consumer_thread.start()


@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
