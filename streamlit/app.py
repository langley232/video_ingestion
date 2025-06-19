import streamlit as st
import requests
import json
import os
import tempfile
from minio import Minio
import logging
from datetime import datetime
import io
import time

# Configuration
INGESTION_ENDPOINT = os.getenv("INGESTION_ENDPOINT", "http://ingestion:8000")

# Updated: OLLAMA_ENDPOINT now points to the vision model (qwen2.5vl:3b)
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama_vision:11434")
# NEW: Endpoint for the embedding model (nomic-embed-text:latest)
OLLAMA_EMBEDDINGS_ENDPOINT = os.getenv("OLLAMA_EMBEDDINGS_ENDPOINT", "http://ollama_embeddings:11434")

STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")
# Note: query_alert service is primarily a consumer, not a direct query API endpoint for alerts
QUERY_ALERT_ENDPOINT = os.getenv("QUERY_ALERT_ENDPOINT", "http://query_alert:8003") 

# MinIO configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MinIO client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)


def get_latest_alerts():
    """Retrieves the latest aggregated alert data from MinIO."""
    try:
        response = minio_client.get_object(
            MINIO_BUCKET, "alerts/latest_sightings.json")
        alert_data = json.loads(response.read().decode())
        response.close()
        response.release_conn()
        return alert_data
    except Exception as e:
        # Use warning as it's expected not to exist initially
        logger.warning(f"Error getting latest alerts (alerts/latest_sightings.json might not exist yet): {str(e)}")
        return None


def query_llm(prompt_chat: str) -> str:
    """Queries the Ollama LLM (Qwen2.5-VL) with context from recent alerts."""
    try:
        # First, get the latest alerts data
        alerts_data = get_latest_alerts()

        # Prepare context from alerts
        alerts_context = "No recent alerts available."
        if alerts_data and "sightings" in alerts_data and alerts_data["sightings"]:
            alerts_context = "Recent alerts:\n"
            for sighting in alerts_data["sightings"]:
                alerts_context += f"- {sighting['object']} detected at {sighting['timestamp']} with {sighting['confidence']:.0%} confidence"
                if sighting.get('details'):
                    alerts_context += f". Details: {sighting['details']}"
                if sighting.get('location') and sighting['location'].get('name'):
                    alerts_context += f" near {sighting['location']['name']}"
                alerts_context += "\n"
        
        # Add summary from latest_sightings.json if available
        if alerts_data and alerts_data.get("summary"):
            alerts_context += f"\nSummary of recent alerts: {alerts_data['summary']}\n"

        # This chat uses OLLAMA_ENDPOINT (now ollama_vision for qwen)
        payload = {
            "model": "qwen2.5vl:3b", # Specific model for vision/chat
            "prompt": f"""You are an AI assistant specialized in analyzing video surveillance footage and detecting suspicious objects, particularly drones and aerial vehicles.
            
            Here is the current alerts data:
            {alerts_context}
            
            Based on this alerts data and your knowledge of video surveillance, answer the user's query: {prompt_chat}
            
            If the query is about recent sightings, use the alerts data above to provide specific details about when and what was detected.
            If no relevant alerts are found in the provided data, clearly state that no matching alerts were found in the recent data.
            If the query involves analyzing specific frames or objects, describe what you would look for in the video.
            
            Provide clear, concise, and accurate responses based on the available data.""",
            "stream": False,
            "keep_alive": "5m" # Keep the model in memory for faster subsequent calls
        }
        response = requests.post(
            f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=90) # Increased timeout
        response.raise_for_status()
        result = response.json().get("response", "No response generated.")
        return result
    except requests.exceptions.Timeout:
        logger.error("Ollama API request timed out during LLM chat.")
        return "Error: LLM chat timed out. Please try again."
    except requests.exceptions.ConnectionError:
        logger.error(f"Error connecting to Ollama vision service: {OLLAMA_ENDPOINT}")
        return "Error: Could not connect to Ollama vision service. Is it running?"
    except Exception as e:
        logger.error(f"Unexpected error in query_llm: {str(e)}")
        return f"Unexpected error querying LLM: {str(e)}"


# Ensure MinIO bucket exists
try:
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
        st.sidebar.success(f"Created MinIO bucket: {MINIO_BUCKET}")
except Exception as e:
    st.sidebar.error(f"Error with MinIO bucket: {e}")

# Streamlit UI
st.title("Video Ingestion and Analysis System")

# Video Upload and Stream
st.header("Video Upload and Stream")
uploaded_file = st.file_uploader(
    "Choose a video file to stream",
    type=["mp4", "avi", "mov", "mpeg4"],
    help="Limit 200MB per file • MP4, AVI, MOV, MPEG4"
)

if uploaded_file is not None:
    st.write(f"Uploaded file: {uploaded_file.name}")
    if st.button("Start Stream"):
        try:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name

            # Stream the video
            with open(tmp_path, 'rb') as video_file:
                files = {'file': (uploaded_file.name, video_file, 'video/mp4')}
                data = {
                    'timestamp': datetime.now().isoformat(),
                    'latitude': 40.7829,
                    'longitude': -73.9654,
                    'location_name': 'Central Park',
                    'description': f'Uploaded video: {uploaded_file.name}'
                }
                response = requests.post(
                    f"{INGESTION_ENDPOINT}/ingest",
                    files=files,
                    data=data,
                    timeout=120 # Increased timeout for ingestion
                )
                response.raise_for_status()
                st.success("Video stream started successfully! Processing will begin shortly.")
        except requests.exceptions.Timeout:
            st.error("Error: Ingestion service timed out. The video might be too large or the service is slow.")
        except requests.exceptions.ConnectionError:
            st.error("Error: Could not connect to the ingestion service. Is it running?")
        except Exception as e:
            st.error(f"Error starting stream: {str(e)}")
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

# Search Frames
st.header("Search Video Frames")
search_query = st.text_input(
    "Enter your search query",
    placeholder="e.g., 'unidentified object over Central Park between 1 PM and 2 PM'"
)


def generate_search_alert_audio(search_results):
    """Generates and stores an audio alert for search results."""
    try:
        # Create alert text with location and timing details
        alert_text = "Search Results Alert: "
        if not search_results:
            alert_text += "No matching videos found for your search."
        else:
            for i, result in enumerate(search_results):
                if i >= 3: break # Limit audio alert to top 3 results for brevity
                alert_text += f"Match {i+1}: "
                if 'metadata' in result and 'location' in result['metadata']:
                    loc = result['metadata']['location']
                    alert_text += f"Object detected near {loc.get('name', 'unknown location')} "
                if 'timestamp' in result['metadata']: # Use metadata timestamp for search results
                    alert_text += f"at {result['metadata']['timestamp']}."
                if 'objects' in result['metadata'] and result['metadata']['objects']:
                    first_obj = result['metadata']['objects'][0]
                    alert_text += f" Detected: {first_obj['name']} with {first_obj['confidence']:.0%} confidence."
                alert_text += " " # Space for next result

        # Generate audio alert
        tts_payload = {
            "text": alert_text.strip(), # Remove trailing space
            "voice_id": "21m00Tcm4TlvDq8ikWAM",
            "model_id": "eleven_turbo_v2_5",
            "stability": 0.5,
            "similarity_boost": 0.75
        }

        # AUDIO_BACKEND_ENDPOINT is defined as an environment variable in docker-compose.yml
        # If running locally without docker-compose, ensure it's set or use a default.
        audio_backend_url = os.getenv('AUDIO_BACKEND_ENDPOINT', 'http://audio_backend:8002') 

        response = requests.post(
            f"{audio_backend_url}/synthesize/",
            json=tts_payload,
            timeout=20
        )

        if response.status_code == 200:
            # Store the audio alert
            audio_path = f"alerts/audio/search_alert_{int(time.time())}.mp3"
            minio_client.put_object(
                MINIO_BUCKET, audio_path,
                io.BytesIO(response.content),
                len(response.content),
                content_type="audio/mpeg"
            )
            return audio_path
        else:
            logger.error(f"TTS for search alert failed with status {response.status_code}: {response.text}")
            return None
    except requests.exceptions.Timeout:
        logger.error("Audio backend request timed out during search alert generation.")
        st.warning("Audio alert generation timed out.")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"Could not connect to audio backend at {os.getenv('AUDIO_BACKEND_ENDPOINT', 'http://audio_backend:8002')}")
        st.warning("Could not connect to audio backend for search alerts.")
        return None
    except Exception as e:
        logger.error(f"Error generating search alert audio: {str(e)}")
    return None


if search_query:
    st.info("Searching for similar frames, please wait...")
    try:
        # Get embeddings for the search query - using the dedicated embedding service
        embedding_response = requests.post(
            f"{OLLAMA_EMBEDDINGS_ENDPOINT}/api/embeddings", # <--- Using dedicated embeddings endpoint
            json={
                "model": "nomic-embed-text:latest",
                "prompt": search_query,
                "keep_alive": "5m"
            },
            timeout=90 # Increased timeout
        )
        embedding_response.raise_for_status()
        embedding = embedding_response.json().get("embedding", [])

        if not embedding:
            st.warning("Could not generate embedding for your query. Please try a different query.")
        else:
            # Search for similar frames in the storage service
            search_response = requests.post(
                f"{STORAGE_ENDPOINT}/search",
                json={"query_embedding": embedding}, # Correct key matching storage/app.py
                timeout=90 # Increased timeout
            )
            search_response.raise_for_status()
            results = search_response.json()

            if results.get("similar_videos"):
                st.success("Search Results Found!")

                # Generate and play audio alert for search results
                audio_path = generate_search_alert_audio(results["similar_videos"])
                if audio_path:
                    try:
                        audio_data = minio_client.get_object(
                            MINIO_BUCKET, audio_path).read()
                        st.audio(audio_data, format="audio/mpeg")
                        st.write("Search Results Audio Alert:")
                    except Exception as audio_e:
                        logger.error(f"Error playing search audio from MinIO: {audio_e}")
                        st.warning("Could not play search alert audio.")

                for result in results["similar_videos"]:
                    with st.expander(f"Video: {result['video_path']} (Similarity: {result['similarity']:.2f})"):
                        # Display video metadata
                        if 'metadata' in result:
                            st.write("### Video Metadata")
                            metadata = result['metadata']

                            # Location information
                            if 'location' in metadata:
                                loc = metadata['location']
                                st.write("**Location:**")
                                st.write(
                                    f"- Latitude: {loc.get('latitude', 'N/A')}")
                                st.write(
                                    f"- Longitude: {loc.get('longitude', 'N/A')}")
                                if 'name' in loc:
                                    st.write(f"- Place: {loc['name']}")

                            # Timing information
                            if 'timestamp' in metadata: # Check for timestamp directly in metadata
                                st.write(f"**Timestamp:** {metadata['timestamp']}")
                            elif 'ingestion_time' in metadata: # Fallback to ingestion_time
                                st.write(f"**Ingestion Time:** {metadata['ingestion_time']}")
                            
                            # Video properties (from video_metadata nested dict)
                            if 'video_metadata' in metadata:
                                vid_meta = metadata['video_metadata']
                                st.write("**Video Properties:**")
                                st.write(
                                    f"- Resolution: {vid_meta.get('width', 'N/A')}x{vid_meta.get('height', 'N/A')}")
                                st.write(f"- FPS: {vid_meta.get('fps', 'N/A')}")
                                st.write(
                                    f"- Duration: {vid_meta.get('duration', 'N/A')} seconds")

                            # Detection details (from objects nested dict or sightings)
                            if 'objects' in metadata or 'sightings' in metadata:
                                st.write("**Detected Objects in this video:**")
                                current_video_detections = metadata.get('objects', [])
                                if not current_video_detections: # Fallback to sightings if objects not top-level
                                    current_video_detections = metadata.get('sightings', [])

                                if current_video_detections:
                                    for obj in current_video_detections:
                                        # Handle both 'name' (from analyze_frame) and 'object' (from sightings list)
                                        obj_name = obj.get('name') or obj.get('object')
                                        obj_confidence = obj.get('confidence')
                                        
                                        if obj_name and obj_confidence is not None:
                                            st.write(
                                                f"- {obj_name} (Confidence: {obj_confidence:.0%})")
                                            if obj.get('details'):
                                                st.write(f"  Details: {obj['details']}")
                                        else:
                                            st.write(f"- Invalid object format: {obj}")
                                else:
                                    st.write("No specific objects reported for this video.")
            else:
                st.write("No matching frames found.")
    except requests.exceptions.Timeout:
        st.error("Error: Search request timed out. Ollama embeddings or Storage service might be slow.")
    except requests.exceptions.ConnectionError:
        st.error("Error: Could not connect to Ollama embeddings or Storage service. Are they running?")
    except Exception as e:
        st.error(f"Error searching frames: {str(e)}")

# Add streaming video metadata display
st.header("Streaming Video Metadata (from Latest Ingested)")
try:
    # Get latest video metadata from MinIO
    # Using recursive=True for prefix 'metadata/' to find all json files in subfolders if any
    objects = minio_client.list_objects(MINIO_BUCKET, prefix="metadata/", recursive=True)
    metadata_files = sorted([
        obj.object_name for obj in objects if obj.object_name.endswith('.json')], reverse=True) # Get latest by name (timestamp)

    if metadata_files:
        latest_metadata_path = metadata_files[0] # Get the very latest metadata file
        response = minio_client.get_object(MINIO_BUCKET, latest_metadata_path)
        metadata = json.loads(response.read().decode())
        response.close()
        response.release_conn()

        st.write("### Latest Stream Metadata")
        st.write(f"**Original Filename:** {metadata.get('original_filename', 'N/A')}")
        st.write(f"**Ingestion ID:** {metadata.get('ingestion_id', 'N/A')}")
        st.write(f"**Ingestion Time:** {metadata.get('ingestion_time', 'N/A')}")

        # Location information
        if 'location' in metadata:
            loc = metadata['location']
            st.write("**Location:**")
            st.write(f"- Latitude: {loc.get('latitude', 'N/A')}")
            st.write(f"- Longitude: {loc.get('longitude', 'N/A')}")
            if 'name' in loc:
                st.write(f"- Place: {loc['name']}")

        # Video properties
        if 'video_metadata' in metadata:
            vid_meta = metadata['video_metadata']
            st.write("**Video Properties:**")
            st.write(
                f"- Resolution: {vid_meta.get('width', 'N/A')}x{vid_meta.get('height', 'N/A')}")
            st.write(f"- FPS: {vid_meta.get('fps', 'N/A')}")
            st.write(f"- Duration: {vid_meta.get('duration', 'N/A')} seconds")

        # Detection details (from this specific video's processing, if query_alert has added it to the metadata)
        # The query_alert service now adds 'sightings' to the video's original metadata when storing an alert
        if 'sightings' in metadata and metadata['sightings']:
            st.write("**Detected Objects (from this video's processing):**")
            for obj in metadata['sightings']: # These are the processed sightings
                obj_name = obj.get('object', 'N/A')
                obj_confidence = obj.get('confidence', 'N/A')
                if obj_name != 'N/A' and obj_confidence != 'N/A':
                    st.write(f"- {obj_name} (Confidence: {obj_confidence:.0%})")
                    if obj.get('details'):
                        st.write(f"  Details: {obj['details']}")
            if metadata.get('summary_from_alert'): # Summary from the alert associated with this video
                st.write(f"**Alert Summary:** {metadata['summary_from_alert']}")
        else:
            st.write("No specific objects reported for this video yet by the analysis system.")
    else:
        st.write("No video metadata found yet. Upload a video to see details.")
except Exception as e:
    st.error(f"Error retrieving streaming metadata: {str(e)}")

# Chat Interface
st.header("Ask About Alerts (General LLM Chat)")
prompt_chat = st.text_input("Ask a question about alerts or sightings")

if prompt_chat:
    try:
        with st.spinner("Getting response from LLM..."):
            result = query_llm(prompt_chat)
            st.write(result)
    except Exception as e:
        st.error(f"Error processing chat: {str(e)}")

# Real-Time Alerts and Map
st.header("Real-Time Alerts and Map")

# Add audio alert playback (from query_alert service)
def get_latest_audio_alert():
    """Retrieves the most recent audio alert from MinIO."""
    try:
        # List objects in the alerts/audio directory
        objects = minio_client.list_objects(
            MINIO_BUCKET, prefix="alerts/audio/", recursive=True)
        audio_files = sorted([
            obj.object_name for obj in objects if obj.object_name.endswith('.mp3')], reverse=True) # Get latest by name (timestamp)

        if audio_files:
            latest_audio_path = audio_files[0]
            response = minio_client.get_object(MINIO_BUCKET, latest_audio_path)
            audio_data = response.read()
            response.close()
            response.release_conn()
            return audio_data
        return None
    except Exception as e:
        logger.error(f"Error getting latest audio alert from MinIO: {str(e)}")
        return None


# Display and play latest audio alert
st.subheader("Latest Alert Audio (from Real-time Detection)")
latest_audio = get_latest_audio_alert()
if latest_audio:
    st.audio(latest_audio, format="audio/mpeg")
    st.info("Audio alert from latest drone detection played.")
else:
    st.info("No real-time audio alerts generated yet. Upload a video with detected objects.")


# Get and display latest alerts (from query_alert service)
st.subheader("Latest Aggregated Alerts")
alerts_data = get_latest_alerts() # This function already logs errors if file not found
if alerts_data and "sightings" in alerts_data and alerts_data["sightings"]:
    for sighting in alerts_data["sightings"]:
        st.write(
            f"- **Object:** {sighting['object']} (Confidence: {sighting['confidence']:.0%})")
        st.write(f"  **Timestamp:** {sighting['timestamp']}")
        if sighting.get('location') and sighting['location'].get('name'):
            st.write(f"  **Location:** {sighting['location']['name']}")
        if sighting.get('details'):
            st.write(f"  **Details:** {sighting['details']}")
        st.markdown("---") # Separator
    if alerts_data.get("summary"):
        st.markdown(f"**Summary:** {alerts_data['summary']}")
else:
    st.write("No recent alerts found. Upload videos to trigger detections.")
