import os
import time
from minio import Minio
from minio.error import S3Error
import requests
import json
import base64
from PIL import Image
import io
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# MinIO configuration
minio_client = Minio(
    endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000").replace("http://", ""),
    access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "admin1234"),
    secure=False
)
bucket_name = os.getenv("MINIO_BUCKET", "videos")

# Create bucket if it doesn't exist
try:
    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)
        logger.info(f"Created MinIO bucket: {bucket_name}")
except S3Error as e:
    logger.error(f"Error creating MinIO bucket: {str(e)}")
    raise

# Ollama configuration
ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
model_name = "llava:13b"

# Storage service configuration
storage_endpoint = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")

def analyze_frame(frame_data: bytes) -> dict:
    """Analyze a frame using ollama's llava:13b model."""
    try:
        # Convert frame to base64
        img = Image.open(io.BytesIO(frame_data))
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        # Query ollama
        payload = {
            "model": model_name,
            "prompt": "Detect objects in the image. Look for drones, missiles, or other suspicious objects. Return a JSON with detected objects and confidence scores.",
            "images": [img_base64],
            "format": "json"
        }
        response = requests.post(f"{ollama_endpoint}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        result = json.loads(response.text.split('\n')[-2])['response']
        return json.loads(result)
    except Exception as e:
        logger.error(f"Error analyzing frame: {str(e)}")
        return {"objects": [], "error": str(e)}

def query_similar_videos(embedding: list) -> list:
    """Query storage service for similar videos."""
    try:
        payload = {"embedding": embedding}
        response = requests.post(f"{storage_endpoint}/search", json=payload, timeout=10)
        response.raise_for_status()
        return response.json().get("similar_videos", [])
    except Exception as e:
        logger.error(f"Error querying similar videos: {str(e)}")
        return []

def store_alert(video_path: str, objects: list, similar_videos: list):
    """Store alert in MinIO."""
    try:
        alert_data = {
            "video_path": video_path,
            "objects": objects,
            "similar_videos": similar_videos,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        alert_path = f"alerts/alert_{int(time.time())}.json"
        with open("/tmp/alert.json", "w") as f:
            json.dump(alert_data, f)
        minio_client.fput_object(bucket_name, alert_path, "/tmp/alert.json")
        logger.info(f"Stored alert: {alert_path}")
    except S3Error as e:
        logger.error(f"Error storing alert: {str(e)}")

def main():
    """Poll MinIO for new videos and process them."""
    last_processed = None
    while True:
        try:
            objects = minio_client.list_objects(bucket_name, prefix="generated/", recursive=True)
            for obj in objects:
                if last_processed and obj.last_modified <= last_processed:
                    continue
                logger.info(f"Processing video: {obj.object_name}")
                # Download video
                response = minio_client.get_object(bucket_name, obj.object_name)
                video_data = response.read()
                response.close()
                response.release_conn()

                # Extract a frame (simplified: assume first frame)
                frame_data = video_data[:1000000]  # Dummy extraction; use opencv in production
                analysis = analyze_frame(frame_data)
                objects_detected = analysis.get("objects", [])

                # Check for suspicious objects
                suspicious = [obj for obj in objects_detected if obj["name"] in ["drone", "missile"] and obj["confidence"] > 0.7]
                if suspicious:
                    # Get embedding from ollama (nomic-embed-text for text description)
                    embedding_payload = {
                        "model": "nomic-embed-text:latest",
                        "prompt": f"Video with objects: {', '.join([o['name'] for o in suspicious])}"
                    }
                    embedding_response = requests.post(f"{ollama_endpoint}/api/embeddings", json=embedding_payload, timeout=10)
                    embedding_response.raise_for_status()
                    embedding = embedding_response.json().get("embedding", [])

                    # Query similar videos
                    similar_videos = query_similar_videos(embedding)

                    # Store alert
                    store_alert(obj.object_name, suspicious, similar_videos)

                last_processed = obj.last_modified
        except S3Error as e:
            logger.error(f"MinIO error: {str(e)}")
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
        time.sleep(10)  # Poll every 10 seconds

if __name__ == "__main__":
    main()
