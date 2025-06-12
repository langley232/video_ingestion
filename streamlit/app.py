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
import datetime # Added for VideoStreamSimulator
import tempfile # Added for temporary file handling

# Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000").replace("http://", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin1234")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")
VIDEO_GEN_ENDPOINT = os.getenv("VIDEO_GEN_ENDPOINT", "http://open_sora_service:8000")
INGESTION_ENDPOINT = os.getenv("INGESTION_ENDPOINT", "http://ingestion:8000")
STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
QUERY_ALERT_ENDPOINT = os.getenv("QUERY_ALERT_ENDPOINT", "http://query_alert:8000") # Added for query_alert service

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
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            st.error(f"Error opening video file: {video_path}")
            return

        st.info(f"Starting stream for {filename}...")
        frame_id = 0
        progress_bar = st.progress(0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            timestamp = datetime.datetime.now().isoformat()
            metadata = {
                "frame_id": frame_id,
                "timestamp": timestamp,
                "latitude": latitude,
                "longitude": longitude,
                "filename": filename
            }

            _, buffer = cv2.imencode('.jpg', frame)
            files = {'frame': ('frame.jpg', buffer.tobytes(), 'image/jpeg')}
            data_payload = {'json': json.dumps(metadata)}

            try:
                response = requests.post(f"{self.ingestion_endpoint}/ingest", files=files, data=data_payload)
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                st.error(f"Error sending frame {frame_id}: {e}")
                break

            frame_id += 1
            if total_frames > 0:
                progress_bar.progress(frame_id / total_frames)
            else:
                progress_bar.progress(frame_id % 100)

            time.sleep(1/30)

        cap.release()
        progress_bar.empty()
        st.success(f"Finished streaming {filename}")

# --- Streamlit App Layout ---
st.set_page_config(page_title="Video Ingestion and Analysis System", layout="wide")
st.title("Video Ingestion and Analysis System")


# --- Video Upload and Stream Section ---
st.header("Video Upload and Stream")
uploaded_file = st.file_uploader("Choose a video file to stream", type=["mp4", "avi", "mov"])

if uploaded_file is not None:
    st.write(f"Uploaded file: {uploaded_file.name}")

    if st.button(f"Stream {uploaded_file.name}"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded_file.name}") as tmpfile:
            tmpfile.write(uploaded_file.getvalue())
            video_path = tmpfile.name

        simulator = VideoStreamSimulator(ingestion_endpoint=INGESTION_ENDPOINT)
        try:
            simulator.stream_video_file(video_path, uploaded_file.name, CENTRAL_PARK_LAT, CENTRAL_PARK_LON)
        finally:
            os.remove(video_path)

# --- Search Video Frames Section ---
st.header("Search Video Frames")
search_query = st.text_input("Enter your search query (e.g., 'unidentified object over Central Park between 1 PM and 2 PM')")

if st.button("Search Frames"):
    if search_query:
        st.info(f"Searching for: {search_query}")
        try:
            # The endpoint is assumed to be http://query_alert:8000/query based on task description
            # Using QUERY_ALERT_ENDPOINT which defaults to http://query_alert:8000
            # and then appending /query
            response = requests.post(f"{QUERY_ALERT_ENDPOINT}/query", json={"query": search_query}, timeout=60)
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
                pass # Ignore if error response is not JSON or doesn't exist
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
        # This chat uses OLLAMA_ENDPOINT for general queries, not query_alert
        payload = {
            "model": "phi3:mini",
            "prompt": f"Based on general knowledge and the context of video surveillance alerts, answer the user's query: {prompt_chat}",
            "stream": False
        }
        response = requests.post(f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        result = response.json().get("response", "No response generated.")
    except Exception as e:
        result = f"Error processing chat: {str(e)}"

    st.session_state.messages.append({"role": "assistant", "content": result})
    with st.chat_message("assistant"):
        st.markdown(result)

# --- Video Generation Section ---
st.header("Video Generation (AI)")
prompt_gen = st.text_input("Enter AI video prompt", value="A drone flying over Central Park, New York City") # Changed label slightly
num_frames_gen = st.number_input("Number of frames for AI video", min_value=1, max_value=120, value=60) # Changed variable name for clarity
resolution_gen = st.selectbox("Resolution for AI video", ["256px", "512px", "768px"], index=1)  # Changed variable name
aspect_ratio_gen = st.selectbox("Aspect Ratio for AI video", ["1:1", "16:9", "9:16", "4:3", "3:4"], index=1) # Changed variable name
seed_gen = st.number_input("Random Seed for AI video", min_value=0, value=42) # Changed variable name
offload_gen = st.checkbox("Enable CPU Offloading for AI video (if GPU memory is low)", value=True) # Changed variable name
gen_latitude = st.number_input("Latitude (for AI video)", min_value=-90.0, max_value=90.0, value=CENTRAL_PARK_LAT, step=0.0001, format="%.4f")
gen_longitude = st.number_input("Longitude (for AI video)", min_value=-180.0, max_value=180.0, value=CENTRAL_PARK_LON, step=0.0001, format="%.4f")

if st.button("Generate AI Video"): # Changed button label
    st.info("AI Video generation started... this may take a while.")
    try:
        response = requests.post(
            f"{VIDEO_GEN_ENDPOINT}/generate-video/",
            json={
                "prompt": prompt_gen,
                "num_frames": num_frames_gen,
                "resolution": resolution_gen,
                "aspect_ratio": aspect_ratio_gen,
                "seed": seed_gen,
                "offload": offload_gen,
                "latitude": gen_latitude,
                "longitude": gen_longitude
            },
            timeout=300
        )
        response.raise_for_status()
        data = response.json()
        video_url = data.get("video_url")
        metadata = data.get("metadata")
        if video_url:
            st.success("AI Video generated successfully!")
            st.write("Generated AI Video URL:", video_url)
            st.write("Associated Metadata:", metadata)
            st.video(video_url)
            st.session_state["last_video_url"] = video_url
            st.session_state["last_metadata"] = metadata
        else:
            st.error(f"AI Video generation failed. Response: {data}")
    except requests.exceptions.Timeout:
        st.error("AI Video generation timed out. The process might be continuing in the background.")
    except Exception as e:
        st.error(f"Error during AI video generation: {str(e)}")

# --- Ingestion of Generated Video ---
if "last_video_url" in st.session_state and st.button("Send Generated AI Video to Ingestion"): # Changed button label
    st.info(f"Sending {st.session_state['last_video_url']} to ingestion service...")
    try:
        video_response = requests.get(st.session_state["last_video_url"], timeout=60)
        video_response.raise_for_status()
        video_content = video_response.content

        generated_video_filename = f"generated_video_{st.session_state['last_metadata'].get('seed', 'unknown_seed')}.mp4"

        with tempfile.NamedTemporaryFile(delete=False, suffix="_generated.mp4") as tmpfile:
            tmpfile.write(video_content)
            temp_video_path = tmpfile.name

        simulator = VideoStreamSimulator(ingestion_endpoint=INGESTION_ENDPOINT)
        try:
            simulator.stream_video_file(
                temp_video_path,
                generated_video_filename,
                st.session_state["last_metadata"].get("latitude", CENTRAL_PARK_LAT),
                st.session_state["last_metadata"].get("longitude", CENTRAL_PARK_LON)
            )
        finally:
            os.remove(temp_video_path)

        st.success("Generated AI video content sent for streaming to ingestion service.")

    except requests.exceptions.Timeout:
        st.error("Timeout when trying to download or send the generated AI video.")
    except Exception as e:
        st.error(f"Failed to send generated AI video to ingestion: {str(e)}")


# --- Real-Time Alerts & Map ---
st.header("Real-Time Alerts and Map")
try:
    response = minio_client.get_object(MINIO_BUCKET, "alerts/latest_sightings.json")
    alert_data = json.loads(response.read().decode())
    response.close()
    response.release_conn()

    st.write("### Alert Summary (from latest_sightings.json)")
    st.text_area("Summary", alert_data.get("summary", "No summary available."), height=100, disabled=True)

    st.write("### Sighting Locations on Map")
    map_center_lat = alert_data.get("metadata", {}).get("sightings", [{}])[0].get("latitude", CENTRAL_PARK_LAT)
    map_center_lon = alert_data.get("metadata", {}).get("sightings", [{}])[0].get("longitude", CENTRAL_PARK_LON)

    m = folium.Map(location=[map_center_lat, map_center_lon], zoom_start=12)

    sightings = alert_data.get("metadata", {}).get("sightings", [])
    if not sightings:
        st.info("No current sightings to display on the map.")
    else:
        for sighting in sightings:
            folium.Marker(
                location=[sighting["latitude"], sighting["longitude"]],
                popup=f"Object: {sighting['object']}<br>Time: {sighting['timestamp']}<br>Confidence: {sighting.get('confidence', 'N/A')}",
                tooltip=sighting['object'],
                icon=folium.Icon(color="red", icon="info-sign")
            ).add_to(m)
        folium_static(m, width=None, height=500)

except Exception as e:
    st.warning(f"Could not load alerts or display map: {str(e)}")
    st.info("If this is the first run, alert data might not be generated yet.")

st.sidebar.info(
    """
    **Video Ingestion & Analysis System**
    - **Upload & Stream**: Upload local video for frame ingestion.
    - **Search Frames**: Query processed frames for specific events.
    - **AI Video Generation**: Create video clips using AI.
    - **Send to Ingestion**: Process AI-generated videos.
    - **Chat (LLM)**: Ask general questions about alerts.
    - **Alerts & Map**: View latest alerts and locations.
    """
)
st.sidebar.markdown(f"**INGESTION_ENDPOINT**: `{INGESTION_ENDPOINT}`")
st.sidebar.markdown(f"**VIDEO_GEN_ENDPOINT**: `{VIDEO_GEN_ENDPOINT}`")
st.sidebar.markdown(f"**OLLAMA_ENDPOINT**: `{OLLAMA_ENDPOINT}`")
st.sidebar.markdown(f"**STORAGE_ENDPOINT**: `{STORAGE_ENDPOINT}`") # Added to sidebar
st.sidebar.markdown(f"**QUERY_ALERT_ENDPOINT**: `{QUERY_ALERT_ENDPOINT}/query`") # Added to sidebar, showing full path

# Ensure MinIO bucket exists
try:
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
        st.sidebar.success(f"MinIO bucket '{MINIO_BUCKET}' created/ensured.")
except Exception as e:
    st.sidebar.error(f"Error with MinIO bucket: {e}")
