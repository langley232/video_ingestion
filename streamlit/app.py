import streamlit as st
import requests
import json
import os
import tempfile
from minio import Minio
import logging
from datetime import datetime

# Configuration
INGESTION_ENDPOINT = os.getenv("INGESTION_ENDPOINT", "http://ingestion:8000")
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")
QUERY_ALERT_ENDPOINT = os.getenv(
    "QUERY_ALERT_ENDPOINT", "http://query_alert:8000/query")

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
    try:
        response = minio_client.get_object(
            MINIO_BUCKET, "alerts/latest_sightings.json")
        alert_data = json.loads(response.read().decode())
        response.close()
        response.release_conn()
        return alert_data
    except Exception as e:
        logger.error(f"Error getting latest alerts: {str(e)}")
        return None


def query_llm(prompt_chat: str) -> str:
    try:
        # First, get the latest alerts data
        alerts_data = get_latest_alerts()

        # Prepare context from alerts
        alerts_context = ""
        if alerts_data and "sightings" in alerts_data:
            alerts_context = "Recent alerts:\n"
            for sighting in alerts_data["sightings"]:
                alerts_context += f"- {sighting['object']} detected at {sighting['timestamp']} with {sighting['confidence']:.0%} confidence"
                if sighting.get('details'):
                    alerts_context += f". Details: {sighting['details']}"
                alerts_context += "\n"

        # This chat uses OLLAMA_ENDPOINT for general queries, not query_alert
        payload = {
            "model": "gemma3:4b",
            "prompt": f"""You are an AI assistant specialized in analyzing video surveillance footage and detecting suspicious objects, particularly drones and aerial vehicles. 
            
            Here is the current alerts data:
            {alerts_context}
            
            Based on this alerts data and your knowledge of video surveillance, answer the user's query: {prompt_chat}
            
            If the query is about recent sightings, use the alerts data above to provide specific details about when and what was detected.
            If no relevant alerts are found, clearly state that no matching alerts were found in the recent data.
            If the query involves analyzing specific frames or objects, describe what you would look for in the video.
            
            Provide clear, concise, and accurate responses based on the available data.""",
            "stream": False
        }
        response = requests.post(
            f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        result = response.json().get("response", "No response generated.")
        return result
    except Exception as e:
        logger.error(f"Error querying LLM: {str(e)}")
        return f"Error querying LLM: {str(e)}"


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
                    data=data
                )
                response.raise_for_status()
                st.success("Video stream started successfully!")
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

if search_query:
    try:
        # Get embeddings for the search query
        embedding_response = requests.post(
            f"{OLLAMA_ENDPOINT}/api/embeddings",
            json={
                "model": "nomic-embed-text:latest",
                "prompt": search_query
            },
            timeout=20
        )
        embedding_response.raise_for_status()
        embedding = embedding_response.json().get("embedding", [])

        # Search for similar frames
        search_response = requests.post(
            f"{STORAGE_ENDPOINT}/search",
            json={"embedding": embedding},
            timeout=20
        )
        search_response.raise_for_status()
        results = search_response.json()

        if results.get("similar_videos"):
            st.write("Search Results:")
            for result in results["similar_videos"]:
                st.write(
                    f"- {result['video_path']} (Similarity: {result['similarity']:.2f})")
        else:
            st.write("No matching frames found.")
    except Exception as e:
        st.error(f"Error searching frames: {str(e)}")

# Chat Interface
st.header("Ask About Alerts (General LLM Chat)")
prompt_chat = st.text_input("Ask a question about alerts or sightings")

if prompt_chat:
    try:
        result = query_llm(prompt_chat)
        st.write(result)
    except Exception as e:
        st.error(f"Error processing chat: {str(e)}")

# Real-Time Alerts and Map
st.header("Real-Time Alerts and Map")

# Get latest alerts
try:
    alerts_data = get_latest_alerts()
    if alerts_data and "sightings" in alerts_data:
        st.write("Latest Alerts:")
        for sighting in alerts_data["sightings"]:
            st.write(
                f"- {sighting['object']} detected at {sighting['timestamp']}")
            if sighting.get('details'):
                st.write(f"  Details: {sighting['details']}")
    else:
        st.write(
            "No alerts available yet. Alerts will appear here once video analysis detects relevant events.")
except Exception as e:
    st.error(f"Error retrieving alerts: {str(e)}")
