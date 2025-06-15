# file identifier : streamlit/app.py
import streamlit as st
import requests
import os
from minio import Minio
import numpy as np
import cv2
import json
import folium
from streamlit_folium import folium_static
import time
import datetime  # Added for VideoStreamSimulator
import tempfile  # Added for temporary file handling
import logging

# Configuration
MINIO_ENDPOINT = os.getenv(
    "MINIO_ENDPOINT", "http://minio:9000").replace("http://", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin1234")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")
INGESTION_ENDPOINT = os.getenv("INGESTION_ENDPOINT", "http://ingestion:8000")
STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
# Added for query_alert service
QUERY_ALERT_ENDPOINT = os.getenv(
    "QUERY_ALERT_ENDPOINT", "http://query_alert:8000")

# Fixed coordinates for Central Park
CENTRAL_PARK_LAT = 40.7829
CENTRAL_PARK_LON = -73.9654

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

# --- VideoStreamSimulator Class ---


class VideoStreamSimulator:
    def __init__(self, ingestion_endpoint):
        self.ingestion_endpoint = ingestion_endpoint

    def stream_video_file(self, video_path, filename, latitude, longitude):
        try:
            st.info(f"Starting upload for {filename}...")

            # Prepare the form data
            files = {'file': (filename, open(video_path, 'rb'), 'video/mp4')}
            data = {
                'timestamp': datetime.datetime.now().isoformat(),
                'latitude': str(latitude),
                'longitude': str(longitude),
                'location_name': 'Central Park',
                'description': f'Uploaded video: {filename}'
            }

            # Send the complete video file
            response = requests.post(
                f"{self.ingestion_endpoint}/ingest",
                files=files,
                data=data
            )
            response.raise_for_status()

            result = response.json()
            st.success(f"Successfully uploaded {filename}")
            st.json(result)

        except Exception as e:
            st.error(f"Error uploading video: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    st.json(e.response.json())
                except:
                    st.text(f"Error response: {e.response.text}")
        finally:
            if 'files' in locals() and 'file' in files:
                files['file'][1].close()


# --- Streamlit App Layout ---
st.set_page_config(
    page_title="Video Ingestion and Analysis System", layout="wide")
st.title("Video Ingestion and Analysis System")


# --- Video Upload and Stream Section ---
st.header("Video Upload and Stream")
uploaded_file = st.file_uploader(
    "Choose a video file to stream", type=["mp4", "avi", "mov"])

if uploaded_file is not None:
    st.write(f"Uploaded file: {uploaded_file.name}")

    if st.button(f"Stream {uploaded_file.name}"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded_file.name}") as tmpfile:
            tmpfile.write(uploaded_file.getvalue())
            video_path = tmpfile.name

        simulator = VideoStreamSimulator(ingestion_endpoint=INGESTION_ENDPOINT)
        try:
            simulator.stream_video_file(
                video_path, uploaded_file.name, CENTRAL_PARK_LAT, CENTRAL_PARK_LON)
        finally:
            os.remove(video_path)

# --- Search Video Frames Section ---
st.header("Search Video Frames")
search_query = st.text_input(
    "Enter your search query (e.g., 'unidentified object over Central Park between 1 PM and 2 PM')")

if st.button("Search Frames"):
    if search_query:
        st.info(f"Searching for: {search_query}")
        try:
            # The endpoint is assumed to be http://query_alert:8000/query based on task description
            # Using QUERY_ALERT_ENDPOINT which defaults to http://query_alert:8000
            # and then appending /query
            response = requests.post(
                f"{QUERY_ALERT_ENDPOINT}/query", json={"query": search_query}, timeout=60)
            response.raise_for_status()
            results = response.json()
            st.success("Search successful!")
            st.json(results)
        except requests.exceptions.Timeout:
            st.error("Search request timed out.")
        except requests.exceptions.RequestException as e:
            st.error(f"Error querying frames: {e}")
            try:
                # Try to display error response from service if available
                st.json(e.response.json())
            except:
                pass  # Ignore if error response is not JSON or doesn't exist
    else:
        st.warning("Please enter a search query.")


# --- Chat Interface ---
st.subheader("Ask About Alerts (General LLM Chat)")
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt_chat := st.chat_input("Ask about recent alerts or sightings (uses general LLM knowledge)"):
    st.session_state.messages.append({"role": "user", "content": prompt_chat})
    with st.chat_message("user"):
        st.markdown(prompt_chat)

    try:
        result = query_llm(prompt_chat)
    except Exception as e:
        result = f"Error processing chat: {str(e)}"

    st.session_state.messages.append({"role": "assistant", "content": result})
    with st.chat_message("assistant"):
        st.markdown(result)

# --- Real-Time Alerts & Map ---
st.header("Real-Time Alerts and Map")
try:
    response = minio_client.get_object(
        MINIO_BUCKET, "alerts/latest_sightings.json")
    alert_data = json.loads(response.read().decode())
    response.close()
    response.release_conn()

    st.write("### Alert Summary (from latest_sightings.json)")
    st.text_area("Summary", alert_data.get(
        "summary", "No summary available."), height=100, disabled=True)

    st.write("### Sighting Locations on Map")
    # Default to Central Park coordinates if no sightings
    map_center_lat = CENTRAL_PARK_LAT
    map_center_lon = CENTRAL_PARK_LON

    # Create map centered on Central Park
    m = folium.Map(location=[map_center_lat, map_center_lon], zoom_start=13)

    # Add sightings to map if available
    if "sightings" in alert_data:
        for sighting in alert_data["sightings"]:
            location = sighting.get("location", {})
            lat = location.get("latitude", map_center_lat)
            lon = location.get("longitude", map_center_lon)
            name = location.get("name", "Unknown Location")

            # Create popup content
            popup_content = f"""
            <b>Object:</b> {sighting.get('object', 'Unknown')}<br>
            <b>Confidence:</b> {sighting.get('confidence', 0):.2%}<br>
            <b>Time:</b> {sighting.get('timestamp', 'Unknown')}<br>
            <b>Details:</b> {sighting.get('details', 'No details available')}
            """

            folium.Marker(
                [lat, lon],
                popup=folium.Popup(popup_content, max_width=300),
                tooltip=name
            ).add_to(m)

    folium_static(m)

except Exception as e:
    st.info("No alerts available yet. Alerts will appear here once video analysis detects relevant events.")
    # Create a default map centered on Central Park
    m = folium.Map(location=[CENTRAL_PARK_LAT,
                   CENTRAL_PARK_LON], zoom_start=13)
    folium.Marker(
        [CENTRAL_PARK_LAT, CENTRAL_PARK_LON],
        popup="Central Park - Default Location",
        tooltip="Central Park"
    ).add_to(m)
    folium_static(m)

st.sidebar.info(
    """
    **Video Ingestion & Analysis System**
    - **Upload & Stream**: Upload local video for frame ingestion.
    - **Search Frames**: Query processed frames for specific events.
    - **Chat (LLM)**: Ask general questions about alerts.
    - **Alerts & Map**: View latest alerts and locations.
    """
)
st.sidebar.markdown(f"**INGESTION_ENDPOINT**: `{INGESTION_ENDPOINT}`")
st.sidebar.markdown(f"**OLLAMA_ENDPOINT**: `{OLLAMA_ENDPOINT}`")
st.sidebar.markdown(f"**STORAGE_ENDPOINT**: `{STORAGE_ENDPOINT}`")
st.sidebar.markdown(
    f"**QUERY_ALERT_ENDPOINT**: `{QUERY_ALERT_ENDPOINT}/query`")

# Ensure MinIO bucket exists
try:
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
        st.sidebar.success(f"MinIO bucket '{MINIO_BUCKET}' created/ensured.")
except Exception as e:
    st.sidebar.error(f"Error with MinIO bucket: {e}")


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
