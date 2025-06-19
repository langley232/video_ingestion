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
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"), # Ensure this is 'minioadmin'
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"), # Ensure this is 'minioadmin'
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
vision_model_name = "qwen2.5vl:3b"
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
        "fixed-wing drone", # Added more specific drone terms
        "rotorcraft",
        "aircraft",
        "flying object",
        "airplane",
        "helicopter"
    ],
    "confidence_threshold": 0.3, # <--- CRITICAL: Lowered for better initial detection
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
            "prompt": """You are an AI assistant analyzing video frames for suspicious objects.
            Given the base64 encoded image, analyze it for any aerial vehicles, drones, or suspicious flying objects.
            
            Focus on detecting:
            1. Small flying objects in the sky
            2. Quadcopter or fixed-wing drone shapes
            3. Objects with propellers or rotors
            4. Objects that appear to be hovering or moving in the air
            5. Any unusual objects that could be drones or UAVs
            
            Return a JSON response in this exact format, with NO additional text or preamble.
            If no suspicious objects are found, return an empty objects array: {"objects": []}.
            
            {
                "objects": [
                    {
                        "name": "object name (e.g., 'drone', 'quadcopter')",
                        "confidence": confidence_score (between 0 and 1),
                        "details": "detailed description of the object and its behavior, like size, shape, color, apparent movement."
                    }
                ]
            }
            Be precise and detailed in your analysis.
            """,
            "images": [img_base64],
            "format": "json", # Use Ollama's format feature for stricter JSON output
            "keep_alive": "5m" # Keep model loaded for a while
        }
        response = requests.post(
            f"{ollama_endpoint}/api/generate", json=payload, timeout=90) # Increased timeout
        response.raise_for_status()

        # Robust JSON parsing for Ollama's response
        full_response_text = response.text
        # Ollama's API with format="json" still might return streamed chunks,
        # but the actual JSON is typically in the last line of a non-streamed response.
        # Let's try to get the 'response' key directly if available, otherwise parse last JSON.
        try:
            # Attempt to parse as direct JSON response from a non-streaming call
            json_data = response.json()
            result_str = json_data.get('response', '')
        except json.JSONDecodeError:
            # Fallback for streamed responses or if 'response' key is not top-level
            result_str = full_response_text.split('\n')[-2] # Assumes last non-empty line
            if not result_str: # If the last-but-one line is empty
                 result_str = full_response_text.strip().split('\n')[-1] # Try the absolute last line

        analysis_result = {"objects": []}
        if result_str:
            try:
                analysis_result = json.loads(result_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode final JSON result from Ollama: {result_str}. Error: {e}")
                # Log the full response text for debugging
                logger.error(f"Full Ollama response text: {full_response_text}")
                return {"objects": [], "error": f"JSON decode error: {e}"}

        # Validate the structure for 'objects' key
        if not isinstance(analysis_result, dict) or "objects" not in analysis_result:
            logger.warning(f"Ollama response did not contain expected 'objects' key or was not a dict: {analysis_result}")
            return {"objects": [], "error": "Unexpected Ollama response format"}

        logger.info(
            f"Frame analysis result: {json.dumps(analysis_result, indent=2)}")
        return analysis_result
    except requests.exceptions.Timeout:
        logger.error("Ollama API request timed out during frame analysis.")
        return {"objects": [], "error": "Ollama timeout"}
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error analyzing frame: {str(e)}")
        return {"objects": [], "error": f"Request error: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error analyzing frame: {str(e)}")
        return {"objects": [], "error": f"Unexpected error: {str(e)}"}


def query_similar_videos(embedding: list) -> list:
    """Queries the storage service for similar videos based on an embedding."""
    try:
        payload = {"query_embedding": embedding} # Changed key to match storage/app.py FastAPI endpoint
        response = requests.post(
            f"{storage_endpoint}/search", json=payload, timeout=20) # Increased timeout
        response.raise_for_status()
        return response.json().get("similar_videos", [])
    except Exception as e:
        logger.error(f"Error querying similar videos from storage service: {str(e)}")
        return []


def summarize_sightings(sightings: list) -> str:
    """Summarizes detected suspicious objects using the summary LLM."""
    try:
        # Construct a clear prompt for summarization
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
            "model": summary_model, # nomic-embed-text:latest - Note: This is an embedding model, not a chat model.
                                    # This should ideally be a text-generation model (e.g., Llama2, Phi3)
                                    # but for now, we'll try to use nomic-embed-text if it has text-gen capability
                                    # or it will error if it's strictly embedding.
            "prompt": prompt,
            "stream": False,
            "keep_alive": "5m"
        }
        response = requests.post(
            f"{ollama_endpoint}/api/generate", json=payload, timeout=45) # Increased timeout
        response.raise_for_status()
        result_json = response.json()
        result = result_json.get('response', '')
        
        if not result: # Fallback if 'response' is empty or not found
            # Attempt more robust parsing for streaming / multi-line outputs
            full_response_text = response.text
            last_line = full_response_text.strip().split('\n')[-1]
            try:
                result = json.loads(last_line).get('response', '')
            except json.JSONDecodeError:
                result = last_line # If not JSON, just take the last line

        logger.info(f"Generated summary: {result}")
        return result
    except requests.exceptions.Timeout:
        logger.error("Ollama API request timed out during summarization.")
        return "Failed to summarize sightings: Ollama timeout."
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error summarizing sightings: {str(e)}")
        return f"Failed to summarize sightings: Request error: {str(e)}."
    except Exception as e:
        logger.error(f"Unexpected error summarizing sightings: {str(e)}")
        return f"Failed to summarize sightings: Unexpected error: {str(e)}."


def store_alert(video_path: str, objects: list, similar_videos: list, metadata: dict, summary: str):
    """Stores a new alert and updates the latest sightings."""
    try:
        # Generate immediate alert text for flying objects
        immediate_alert_text = "Alert! Alert! There is a flying object detected! Check the system for details."
        
        # Generate detailed alert text for speech synthesis
        alert_text = f"ALERT: {summary}"
        if metadata.get("sightings"): # Use sightings from the processed metadata
            for sighting in metadata["sightings"]:
                alert_text += f" Detected {sighting['object']} with {sighting['confidence']:.0%} confidence. "
                if sighting.get("details"):
                    alert_text += f"Details: {sighting['details']}. "

        # Attempt text-to-speech synthesis for immediate alert
        audio_path = None
        try:
            logger.info(f"Generating immediate speech alert: {immediate_alert_text}")
            tts_payload = {
                "text": immediate_alert_text,
                "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel voice
                "model_id": "eleven_turbo_v2_5",
                "stability": 0.5,
                "similarity_boost": 0.75
            }

            # Add retry logic for TTS
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
                        # Store the audio alert
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
                # Generate a fallback alert if TTS fails
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
        # Ensure 'timestamp' field is consistent (from video metadata)
        alert_data = {
            "video_path": video_path,
            "objects": objects, # The suspicious objects list
            "similar_videos": similar_videos,
            "metadata_from_video": metadata, # Original video metadata
            "summary": summary,
            "alert_text": alert_text,
            "audio_path": audio_path,
            "timestamp": metadata.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S")), # Use video timestamp
            "alert_generation_time": time.strftime("%Y-%m-%d %H:%M:%S"), # When this alert was generated
            "alert_status": "success" if audio_path else "warning"
        }

        # Store individual alert
        alert_path = f"alerts/alert_{int(time.time())}.json"
        with open("/tmp/alert.json", "w") as f:
            json.dump(alert_data, f)
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

            # Add new suspicious objects to the sightings list
            new_sightings_entries = []
            for obj in objects: # objects here are the 'suspicious' ones
                new_sightings_entries.append({
                    "object": obj["name"],
                    "confidence": obj["confidence"],
                    "details": obj.get("details", ""),
                    "video_path": video_path,
                    "timestamp": metadata.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S")),
                    "location": metadata.get("location", {})
                })

            current_sightings_data["sightings"].extend(new_sightings_entries)
            # Keep only the N most recent sightings if list gets too long
            # Example: keep last 10 sightings
            current_sightings_data["sightings"] = current_sightings_data["sightings"][-10:]

            # Recalculate summary for latest_sightings.json based on ALL current sightings
            # Pass only the 'sightings' list to the summarizer
            updated_summary = summarize_sightings(current_sightings_data["sightings"])
            current_sightings_data["summary"] = updated_summary
            current_sightings_data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

            # Write back to MinIO
            with open("/tmp/latest_sightings.json", "w") as f:
                json.dump(current_sightings_data, f, indent=2) # Added indent for readability
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

        # Get video metadata from MinIO
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


        # Get video content from MinIO
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
        
        # Handle potential error from analyze_frame
        if "error" in analysis:
            logger.error(f"Frame analysis error: {analysis['error']}")
            return

        logger.info(
            f"Frame analysis results (raw): {json.dumps(objects_detected, indent=2)}")

        # Check for suspicious objects based on name and confidence
        suspicious = [
            obj for obj in objects_detected
            if isinstance(obj, dict) and # Ensure obj is a dict
               "name" in obj and "confidence" in obj and # Ensure keys exist
               any(target.lower() in obj["name"].lower() for target in DETECTION_CONFIG["target_objects"])
               and obj["confidence"] > DETECTION_CONFIG["confidence_threshold"]
        ]
        logger.info(
            f"Detected suspicious objects (filtered): {json.dumps(suspicious, indent=2)}")

        if suspicious:
            # Use location from metadata if available, otherwise default
            location = video_metadata.get("location", {
                "latitude": 40.7829,
                "longitude": -73.9654,
                "name": "Central Park"
            })
            logger.info(f"Using location for alert: {location}")

            # Create detailed description for summarization
            detection_details = []
            for obj in suspicious:
                details = f"{obj['name']} (confidence: {obj['confidence']:.2f})"
                if 'details' in obj:
                    details += f" - {obj['details']}"
                detection_details.append(details)

            detection_text = " | ".join(detection_details)
            logger.info(f"Detection details text for embeddings: {detection_text}")

            # Get embeddings for similarity search using the detected objects
            embedding = None
            try:
                embedding_response = requests.post(
                    f"{ollama_endpoint}/api/embeddings",
                    json={
                        "model": "nomic-embed-text:latest",
                        "prompt": f"Video frame analysis: {detection_text}. Location: {location.get('name', 'unknown')}"
                    },
                    timeout=20
                )
                embedding_response.raise_for_status()
                embedding = embedding_response.json().get("embedding", [])
                logger.info("Generated embeddings for similarity search from detected objects.")
            except Exception as e:
                logger.error(f"Error generating embedding for suspicious object: {str(e)}")
                embedding = None # Ensure embedding is None if failed

            similar_videos = []
            if embedding: # Only query if embedding was successful
                similar_videos = query_similar_videos(embedding)
                logger.info(
                    f"Found similar videos: {json.dumps(similar_videos, indent=2)}")

            # Create sightings with enhanced metadata
            sightings = []
            for obj in suspicious:
                sighting = {
                    "object": obj["name"],
                    "confidence": obj["confidence"],
                    "details": obj.get("details", ""),
                    "video_path": video_path,
                    "timestamp": video_metadata.get("timestamp", timestamp), # Use video_metadata timestamp primarily
                    "location": location,
                    "video_metadata": video_metadata.get("video_metadata", {})
                }
                sightings.append(sighting)

            if sightings: # Only store alert if there are actual sightings
                # Pass the sightings list *into* the metadata that goes to store_alert
                video_metadata_with_sightings = video_metadata.copy()
                video_metadata_with_sightings["sightings"] = sightings # Add the list of suspicious objects here for summary
                
                summary = summarize_sightings(sightings) # Summarize based on the raw sightings
                logger.info(f"Generated summary: {summary}")
                
                alert_data = store_alert(video_path, suspicious, similar_videos, video_metadata_with_sightings, summary)
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

    # Initial subscription attempt with retries
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
                # Continue without subscribing, rely on subsequent polls to implicitly re-subscribe
                pass 

    try:
        while True:
            msg = consumer.poll(1000) # Poll for messages

            if msg is None:
                logger.debug("No message received, continuing to poll...")
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    logger.debug("Reached end of partition, continuing...")
                    continue
                else:
                    logger.error(f"Kafka consumer error: {msg.error()}")
                    continue

            try:
                data = msg.value # Message is already deserialized by value_deserializer
                logger.info(f"Received message from Kafka: {data}")

                video_path = data.get('video_path')
                # Use timestamp from the message, which comes from ingestion metadata
                timestamp = data.get('timestamp', time.strftime("%Y-%m-%d %H:%M:%S")) 

                if video_path:
                    process_video(video_path, timestamp)
                else:
                    logger.warning("Received message with no video_path")

            except Exception as e:
                logger.error(f"Error processing Kafka message: {str(e)}")
                # Continue to next message, don't crash loop

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
    # This ensures uvicorn runs the FastAPI app and the consumer thread starts
    uvicorn.run(app, host="0.0.0.0", port=8003) # query_alert runs on port 8003
