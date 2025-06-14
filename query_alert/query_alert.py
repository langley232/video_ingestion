#file identifier: query_alert/query_alert.py
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

app = FastAPI()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

minio_client = Minio(
    endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000").replace("http://", ""),
    access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "admin1234"),
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
vision_model_name = "moondream:1.8b" # Changed from llava_model
summary_model = "nomic-embed-text:latest"

storage_endpoint = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")
AUDIO_BACKEND_ENDPOINT = os.getenv("AUDIO_BACKEND_ENDPOINT", "http://audio_backend:8000")

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
            "model": vision_model_name, # Changed from llava_model
            "prompt": "Detect objects in the image. Look for drones, people (e.g., resembling Tom Cruise), or other suspicious objects. Return a JSON with detected objects and confidence scores.",
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
    try:
        payload = {"embedding": embedding}
        response = requests.post(f"{storage_endpoint}/search", json=payload, timeout=10)
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
        response = requests.post(f"{ollama_endpoint}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        result = json.loads(response.text.split('\n')[-2])['response']
        return result
    except Exception as e:
        logger.error(f"Error summarizing sightings: {str(e)}")
        return "Failed to summarize sightings."

def store_alert(video_path: str, objects: list, similar_videos: list, metadata: dict, summary: str):
    try:
        alert_text_for_speech = summary # Use the generated summary for TTS
        audio_synthesis_status = "not_attempted"

        if alert_text_for_speech:
            try:
                logger.info(f"Attempting text-to-speech for alert: {alert_text_for_speech[:50]}...") # Log first 50 chars
                tts_payload = {"text": alert_text_for_speech}
                # Using default voice, model, etc., as defined in audio_backend
                response = requests.post(f"{AUDIO_BACKEND_ENDPOINT}/synthesize/", json=tts_payload, timeout=20)

                if response.status_code == 200:
                    # We are not saving the audio bytes here, just noting success.
                    # The audio is streamed by audio_backend but not stored by query_alert.
                    audio_synthesis_status = "successful"
                    logger.info("Text-to-speech synthesis successful.")
                    # If we were to save it, this is where we'd handle response.content
                else:
                    audio_synthesis_status = f"failed_status_{response.status_code}"
                    logger.error(f"Text-to-speech synthesis failed with status {response.status_code}: {response.text}")
            except requests.exceptions.RequestException as e:
                audio_synthesis_status = "failed_exception"
                logger.error(f"Text-to-speech synthesis request failed: {str(e)}")
        else:
            audio_synthesis_status = "no_text_provided"
            logger.info("No alert text provided for speech synthesis.")

        alert_data = {
            "video_path": video_path,
            "objects": objects,
            "similar_videos": similar_videos,
            "metadata": metadata,
            "summary": summary,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "audio_synthesis_status": audio_synthesis_status # Add status to alert data
        }
        alert_path = f"alerts/alert_{int(time.time())}.json"
        with open("/tmp/alert.json", "w") as f:
            json.dump(alert_data, f)
        minio_client.fput_object(bucket_name, alert_path, "/tmp/alert.json")
        logger.info(f"Stored alert: {alert_path}")
        return alert_data
    except S3Error as e:
        logger.error(f"Error storing alert: {str(e)}")
        return None

@app.get("/health")
async def health_check():
    return {"status": "ok"}

def main():
    last_processed = None
    while True:
        try:
            objects = minio_client.list_objects(bucket_name, prefix="generated_videos/", recursive=True)
            sightings = []
            for obj in objects:
                if last_processed and obj.last_modified <= last_processed:
                    continue
                logger.info(f"Processing video: {obj.object_name}")

                response = minio_client.get_object(bucket_name, obj.object_name)
                video_data = response.read()
                response.close()
                response.release_conn()

                frame_data = extract_frame(video_data)
                if not frame_data:
                    logger.warning(f"Failed to extract frame from {obj.object_name}")
                    continue

                analysis = analyze_frame(frame_data)
                objects_detected = analysis.get("objects", [])

                suspicious = [obj for obj in objects_detected if obj["name"] in ["drone", "Tom Cruise"] and obj["confidence"] > 0.7]
                if suspicious:
                    metadata_path = f"metadata/{obj.object_name.split('/')[-1].replace('.mp4', '.json')}"
                    try:
                        metadata_response = minio_client.get_object(bucket_name, metadata_path)
                        metadata = json.loads(metadata_response.read().decode())
                        metadata_response.close()
                        metadata_response.release_conn()
                    except S3Error:
                        metadata = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "latitude": 0.0, "longitude": 0.0}

                    embedding_response = requests.post(
                        f"{ollama_endpoint}/api/embeddings",
                        json={
                            "model": "nomic-embed-text:latest",
                            "prompt": f"Video with objects: {', '.join([o['name'] for o in suspicious])}"
                        },
                        timeout=20
                    )
                    embedding_response.raise_for_status()
                    embedding = embedding_response.json().get("embedding", [])

                    similar_videos = query_similar_videos(embedding)

                    for obj in suspicious:
                        sightings.append({
                            "object": obj["name"],
                            "confidence": obj["confidence"],
                            "video_path": obj.object_name,
                            "timestamp": metadata["timestamp"],
                            "latitude": metadata["latitude"],
                            "longitude": metadata["longitude"]
                        })

                last_processed = obj.last_modified

            if sightings:
                summary = summarize_sightings(sightings)
                alert_data = store_alert("multiple_videos", suspicious, similar_videos, {"sightings": sightings}, summary)
                if alert_data:
                    minio_client.fput_object(bucket_name, "alerts/latest_sightings.json", "/tmp/alert.json")

        except S3Error as e:
            logger.error(f"MinIO error: {str(e)}")
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
        time.sleep(10)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
