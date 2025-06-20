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


def extract_frame(video_data: bytes) -> bytes:
    """Extracts the first frame from video content."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        temp_file.write(video_data)
        temp_file.flush()
        temp_path = temp_file.name

    cap = cv2.VideoCapture(temp_path)
    if not cap.isOpened():
        logger.error(f"Could not open video file: {temp_path}")
        os.unlink(temp_path) # Clean up temp file
        return None

    ret, frame = cap.read()
    cap.release()
    os.unlink(temp_path) # Clean up temp file

    if ret:
        _, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes()
    return None


def analyze_frame(frame_data: bytes) -> dict:
    """Analyzes a frame using Ollama's Qwen2.5-VL model for object detection."""
    try:
        img_base64 = base64.b64encode(frame_data).decode("utf-8")
        payload = {
            "model": DETECTION_CONFIG["model"],
            "prompt": """Analyze the image for aerial vehicles like drones, UAVs, quadcopters, aircraft, or any suspicious flying objects.
            If detected, list them in a JSON array. Each object should have a "name" (e.g., "drone", "quadcopter"), "confidence" (0-1), and "details" (description).
            If nothing is found, return {"objects": []}.
            """,
            "images": [img_base64],
            "format": "json", # Request JSON format explicitly
            "stream": False,
            "keep_alive": "5m"
        }
        response = requests.post(
            f"{OLLAMA_VISION_ENDPOINT}/api/generate", json=payload, timeout=90) # Route to vision endpoint
        response.raise_for_status()

        full_response_text = response.text
        analysis_result = {"objects": []} # Default to empty result

        try:
            # First, try to parse the entire response as JSON (if stream=False, it should be)
            json_data = response.json()
            # The actual generated text might be in the 'response' key
            generated_text = json_data.get('response', '').strip()
            
            if generated_text:
                # Try to load the 'response' content as JSON
                analysis_result = json.loads(generated_text)
            else:
                # If 'response' is empty, it means no objects were detected or model didn't generate structured output
                logger.debug("Ollama 'response' field was empty, assuming no objects detected or non-compliant output.")

        except json.JSONDecodeError as e_outer:
            # If the entire response text isn't a valid JSON (e.g., streamed chunks, or extra text)
            # Try to find a JSON-like string within the full text
            logger.warning(f"Full Ollama response not direct JSON. Attempting regex parse. Error: {e_outer}")
            json_match = re.search(r'\{.*\}', full_response_text, re.DOTALL)
            if json_match:
                json_string_from_regex = json_match.group(0)
                try:
                    analysis_result = json.loads(json_string_from_regex)
                except json.JSONDecodeError as e_inner:
                    logger.error(f"Failed to decode JSON from regex match: '{json_string_from_regex}'. Error: {e_inner}")
                    logger.error(f"Full Ollama response text that failed regex parse: '{full_response_text}'")
                    return {"objects": [], "error": f"JSON parse error after regex: {e_inner}"}
            else:
                logger.warning(f"Could not find valid JSON structure in Ollama response: '{full_response_text}'")
                return {"objects": [], "error": "No valid JSON structure found in Ollama response."}
        
        # Final validation of the structure
        if not isinstance(analysis_result, dict) or "objects" not in analysis_result or not isinstance(analysis_result["objects"], list):
            logger.warning(f"Parsed Ollama response did not contain expected 'objects' list: {analysis_result}")
            return {"objects": [], "error": "Unexpected Ollama response format after parsing."}

        logger.info(
            f"Frame analysis result: {json.dumps(analysis_result, indent=2)}")
        return analysis_result
    except requests.exceptions.Timeout:
        logger.error("Ollama API request timed out during frame analysis.")
        return {"objects": [], "error": "Ollama timeout"}
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error analyzing frame: {str(e)}. Response: {e.response.text if e.response else 'N/A'}")
        return {"objects": [], "error": f"Request error: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error analyzing frame: {str(e)}")
        return {"objects": [], "error": f"Unexpected error: {str(e)}"}


def query_similar_videos(embedding: list) -> list:
    """Queries the storage service for similar videos based on an embedding."""
    try:
        payload = {"query_embedding": embedding}
        response = requests.post(
            f"{storage_endpoint}/search", json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("similar_videos", [])
    except requests.exceptions.Timeout:
        logger.error("Storage service timed out during similarity search.")
        return []
    except requests.exceptions.ConnectionError:
        logger.error(f"Could not connect to storage service at {storage_endpoint}")
        return []
    except Exception as e:
        logger.error(f"Error querying similar videos from storage service: {str(e)}")
        return []


def summarize_sightings(sightings: list) -> str:
    """Summarizes detected suspicious objects using the summary LLM."""
    try:
        sightings_str = "\n".join([
            f"- {sighting['object']} (Confidence: {sighting['confidence']:.2f}) "
            f"at {sighting['timestamp']} near {sighting['location'].get('name', 'unknown location')}. "
            f"Details: {sighting.get('details', 'N/A')}"
            for sighting in sightings
        ])
        
        prompt = f"""Summarize the following detected objects. Focus on type, confidence, time, and location.
        \n\nSightings:\n{sightings_str}\n\nProvide a concise, factual summary in natural language. Do not make up information.
        """
        payload = {
            "model": summary_model, # This is nomic-embed-text
            "prompt": prompt,
            "stream": False,
            "keep_alive": "5m"
        }
        # Route summarization request to the dedicated embedding service
        response = requests.post(
            f"{OLLAMA_EMBEDDINGS_ENDPOINT}/api/generate", json=payload, timeout=60) # Route to embeddings endpoint
        response.raise_for_status()
        result_json = response.json()
        result = result_json.get('response', '').strip()

        if not result:
            full_response_text = response.text
            last_line = full_response_text.strip().split('\n')[-1]
            try:
                result = json.loads(last_line).get('response', '').strip()
            except json.JSONDecodeError:
                result = last_line.strip()

        logger.info(f"Generated summary: {result}")
        return result
    except requests.exceptions.Timeout:
        logger.error("Ollama API request timed out during summarization.")
        return "Failed to summarize sightings: Ollama timeout."
    except requests.exceptions.ConnectionError:
        logger.error(f"Could not connect to Ollama embeddings service at {OLLAMA_EMBEDDINGS_ENDPOINT}")
        return "Failed to summarize sightings: Connection error to embeddings service."
    except Exception as e:
        logger.error(f"Unexpected error summarizing sightings: {str(e)}")
        return f"Failed to summarize sightings: Unexpected error: {str(e)}."


def store_alert(video_path: str, objects: list, similar_videos: list, metadata: dict, summary: str):
    """Stores a new alert and updates the latest sightings."""
    try:
        immediate_alert_text = "Alert! Alert! There is a flying object detected! Check the system for details."
        
        alert_text = f"ALERT: {summary}"
        if metadata.get("sightings"):
            for sighting in metadata["sightings"]:
                alert_text += f" Detected {sighting['object']} with {sighting['confidence']:.0%} confidence. "
                if sighting.get("details"):
                    alert_text += f"Details: {sighting['details']}. "

        audio_path = None
        try:
            logger.info(f"Generating immediate speech alert: {immediate_alert_text}")
            tts_payload = {
                "text": immediate_alert_text,
                "voice_id": "21m00Tcm4TlvDq8ikWAM",
                "model_id": "eleven_turbo_v2_5",
                "stability": 0.5,
                "similarity_boost": 0.75
            }

            max_retries = 3
            retry_delay = 2

            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        f"{AUDIO_BACKEND_ENDPOINT}/synthesize/",
                        json=tts_payload,
                        timeout=20
                    )

                    if response.status_code == 200:
                        audio_path = f"alerts/audio/alert_{int(time.time())}.mp3"
                        minio_client.put_object(
                            bucket_name, audio_path,
                            io.BytesIO(response.content),
                            len(response.content),
                            content_type="audio/mpeg"
                        )
                        logger.info(
                            f"Successfully generated and stored immediate audio alert: {audio_path}")
                        break
                    else:
                        logger.warning(
                            f"Speech synthesis attempt {attempt + 1} failed with status {response.status_code}. Response: {response.text}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                        else:
                            logger.error(
                                f"All speech synthesis attempts failed. Last status: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    logger.warning(
                        f"Speech synthesis attempt {attempt + 1} failed with error: {str(e)}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    else:
                        logger.error(
                            f"All speech synthesis attempts failed. Last error: {str(e)}")

            if not audio_path:
                fallback_alert = "ALERT: Suspicious object detected. Please check the alert details in the system."
                tts_payload["text"] = fallback_alert
                try:
                    response = requests.post(
                        f"{AUDIO_BACKEND_ENDPOINT}/synthesize/",
                        json=tts_payload,
                        timeout=20
                    )
                    if response.status_code == 200:
                        audio_path = f"alerts/audio/fallback_alert_{int(time.time())}.mp3"
                        minio_client.put_object(
                            bucket_name, audio_path,
                            io.BytesIO(response.content),
                            len(response.content),
                            content_type="audio/mpeg"
                        )
                        logger.info(
                            f"Generated fallback audio alert: {audio_path}")
                except Exception as e:
                    logger.error(
                        f"Failed to generate fallback audio alert: {str(e)}")

        except Exception as e:
            logger.error(f"Error in speech synthesis process: {str(e)}")

        # Store alert data
        alert_data = {
            "video_path": video_path,
            "objects": objects,
            "similar_videos": similar_videos,
            "metadata_from_video": metadata,
            "summary": summary,
            "alert_text": alert_text,
            "audio_path": audio_path,
            "timestamp": metadata.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S")),
            "alert_generation_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "alert_status": "success" if audio_path else "warning"
        }

        alert_path = f"alerts/alert_{int(time.time())}.json"
        with open("/tmp/alert.json", "w") as f:
            json.dump(alert_data, f, indent=2)
        minio_client.fput_object(bucket_name, alert_path, "/tmp/alert.json")
        logger.info(f"Stored individual alert: {alert_path}")


        # Update latest sightings (for Streamlit LLM chat context)
        try:
            current_sightings_data = {"sightings": [], "summary": "", "last_updated": ""}
            try:
                response = minio_client.get_object(bucket_name, "alerts/latest_sightings.json")
                current_sightings_data = json.loads(response.read().decode())
                response.close()
                response.release_conn()
            except S3Error as e:
                if e.code == 'NoSuchKey':
                    logger.info("latest_sightings.json not found, creating new.")
                else:
                    logger.error(f"Error getting existing latest_sightings.json: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error reading latest_sightings.json: {str(e)}")

            new_sightings_entries = []
            for obj in objects: # objects here are the 'suspicious' ones
                new_sighting = {
                    "object": obj["name"],
                    "confidence": obj["confidence"],
                    "details": obj.get("details", ""),
                    "video_path": video_path,
                    "timestamp": metadata.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S")),
                    "location": metadata.get("location", {})
                }
                if "ingestion_id" in metadata: new_sighting["ingestion_id"] = metadata["ingestion_id"]
                if "original_filename" in metadata: new_sighting["original_filename"] = metadata["original_filename"]
                if "video_metadata" in metadata: new_sighting["video_properties"] = metadata["video_metadata"]
                
                new_sightings_entries.append(new_sighting)

            current_sightings_data["sightings"].extend(new_sightings_entries)
            current_sightings_data["sightings"] = current_sightings_data["sightings"][-10:] # Keep last 10 sightings

            updated_summary = summarize_sightings(current_sightings_data["sightings"])
            current_sightings_data["summary"] = updated_summary
            current_sightings_data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

            with open("/tmp/latest_sightings.json", "w") as f:
                json.dump(current_sightings_data, f, indent=2)
            minio_client.fput_object(
                bucket_name, "alerts/latest_sightings.json", "/tmp/latest_sightings.json")
            logger.info("Updated latest_sightings.json in MinIO.")

        except Exception as e:
            logger.error(f"Error updating latest sightings: {str(e)}")

        return alert_data
    except Exception as e:
        logger.error(f"Error storing alert: {str(e)}")
        return None


def process_video(video_path: str, timestamp: str):
    """Processes a video from MinIO for object detection and alert generation."""
    try:
        logger.info(f"Processing video: {video_path}")

        metadata_minio_path = video_path.replace(
            "generated_videos/", "metadata/").replace(".mp4", ".json")
        video_metadata = {}
        try:
            metadata_response = minio_client.get_object(
                bucket_name, metadata_minio_path)
            video_metadata = json.loads(metadata_response.read().decode())
            metadata_response.close()
            metadata_response.release_conn()
            logger.info(
                f"Retrieved metadata for {video_path}: {video_metadata}")
        except S3Error as e:
            if e.code == 'NoSuchKey':
                logger.warning(f"No metadata found at {metadata_minio_path} for {video_path}, using empty dict.")
            else:
                logger.error(f"Error retrieving metadata from MinIO {metadata_minio_path}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error retrieving metadata: {str(e)}")

        response = minio_client.get_object(bucket_name, video_path)
        video_data = response.read()
        response.close()
        response.release_conn()
        logger.info(f"Retrieved video data for {video_path}")

        frame_data = extract_frame(video_data)
        if not frame_data:
            logger.warning(f"Failed to extract frame from {video_path}")
            return
        logger.info(f"Successfully extracted frame from {video_path}")

        analysis = analyze_frame(frame_data)
        objects_detected = analysis.get("objects", [])
        
        if "error" in analysis:
            logger.error(f"Frame analysis error: {analysis['error']}")
            return

        logger.info(
            f"Frame analysis results (raw): {json.dumps(objects_detected, indent=2)}")

        suspicious = [
            obj for obj in objects_detected
            if isinstance(obj, dict) and
               "name" in obj and "confidence" in obj and
               any(target.lower() in obj["name"].lower() for target in DETECTION_CONFIG["target_objects"])
               and obj["confidence"] > DETECTION_CONFIG["confidence_threshold"]
        ]
        logger.info(
            f"Detected suspicious objects (filtered): {json.dumps(suspicious, indent=2)}")

        if suspicious:
            location = video_metadata.get("location", {
                "latitude": 40.7829,
                "longitude": -73.9654,
                "name": "Central Park"
            })
            logger.info(f"Using location for alert: {location}")

            detection_details = []
            for obj in suspicious:
                details = f"{obj['name']} (confidence: {obj['confidence']:.2f})"
                if 'details' in obj:
                    details += f" - {obj['details']}"
                detection_details.append(details)

            detection_text = " | ".join(detection_details)
            logger.info(f"Detection details text for embeddings: {detection_text}")

            embedding = None
            try:
                # Use the specific embeddings endpoint
                ollama_embeddings_endpoint = os.getenv("OLLAMA_EMBEDDINGS_ENDPOINT", "http://ollama_embeddings:11434")
                embedding_response = requests.post(
                    f"{ollama_embeddings_endpoint}/api/embeddings",
                    json={
                        "model": "nomic-embed-text:latest",
                        "prompt": f"Video frame analysis: {detection_text}. Location: {location.get('name', 'unknown')}"
                    },
                    timeout=30
                )
                embedding_response.raise_for_status()
                embedding = embedding_response.json().get("embedding", [])
                logger.info("Generated embeddings for similarity search from detected objects.")
            except requests.exceptions.Timeout:
                logger.error("Ollama embeddings service timed out during embedding generation.")
                embedding = None
            except requests.exceptions.ConnectionError:
                logger.error(f"Could not connect to Ollama embeddings service at {ollama_embeddings_endpoint}")
                embedding = None
            except Exception as e:
                logger.error(f"Error generating embedding for suspicious object: {str(e)}")
                embedding = None 

            similar_videos = []
            if embedding:
                similar_videos = query_similar_videos(embedding)
                logger.info(
                    f"Found similar videos: {json.dumps(similar_videos, indent=2)}")

            sightings = []
            for obj in suspicious:
                sighting = {
                    "object": obj["name"],
                    "confidence": obj["confidence"],
                    "details": obj.get("details", ""),
                    "video_path": video_path,
                    "timestamp": video_metadata.get("timestamp", timestamp),
                    "location": location,
                    "video_metadata": video_metadata.get("video_metadata", {})
                }
                sightings.append(sighting)

            if sightings:
                video_metadata_for_alert = video_metadata.copy()
                video_metadata_for_alert["sightings"] = sightings
                
                summary = summarize_sightings(sightings)
                logger.info(f"Generated summary: {summary}")
                
                alert_data = store_alert(video_path, suspicious, similar_videos, video_metadata_for_alert, summary)
                logger.info(
                    f"Generated alert for {video_path}: {json.dumps(alert_data, indent=2)}")
                return alert_data
            else:
                logger.info(f"No sufficient suspicious objects detected in {video_path} to generate alert.")

        else:
            logger.info(f"No suspicious objects detected in {video_path} above threshold {DETECTION_CONFIG['confidence_threshold']}.")

    except Exception as e:
        logger.error(f"Error processing video {video_path}: {str(e)}")
        return None


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
                pass 

    try:
        while True:
            msg = consumer.poll(1000) # Poll for messages (timeout in milliseconds)

            if msg is None:
                logger.debug("No message received, continuing to poll...")
                continue
            if msg.error() is not None:
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    logger.debug("Reached end of partition, continuing...")
                    continue
                else:
                    logger.error(f"Kafka consumer error: {msg.error()}")
                    continue

            try:
                data = json.loads(msg.value().decode("utf-8")) # Access the value from the Message object
                logger.info(f"Received message from Kafka: {data}")

                video_path = data.get('video_path')
                timestamp = data.get('timestamp', time.strftime("%Y-%m-%d %H:%M:%S")) 

                if video_path:
                    process_video(video_path, timestamp)
                else:
                    logger.warning("Received message with no video_path")

            except Exception as e:
                logger.error(f"Error processing Kafka message: {str(e)}")
                continue

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
