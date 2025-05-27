import streamlit as st
import requests
import os
from minio import Minio
import numpy as np
import cv2
import json
import folium
from streamlit_folium import folium_static

# Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000").replace("http://", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin1234")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")
VIDEO_GEN_ENDPOINT = os.getenv("VIDEO_GEN_ENDPOINT", "http://open_sora_service:8000")
INGESTION_ENDPOINT = os.getenv("INGESTION_ENDPOINT", "http://ingestion:8000")
STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "http://storage:8001")
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

st.set_page_config(page_title="Video Ingestion System", layout="wide")

st.title("Video Ingestion System")

# Chat Interface
st.subheader("Ask About Alerts")
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about recent alerts or sightings"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        payload = {
            "model": "phi3:mini",
            "prompt": f"Answer the user's query based on recent alerts: {prompt}",
            "stream": False
        }
        response = requests.post(f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=10)
        response.raise_for_status()
        result = response.json().get("response", "No response generated.")
    except Exception as e:
        result = f"Error: {str(e)}"

    st.session_state.messages.append({"role": "assistant", "content": result})
    with st.chat_message("assistant"):
        st.markdown(result)

# Video Generation
st.header("Video Generation")
prompt = st.text_input("Enter video prompt", value="A drone flying over a city")
num_frames = st.number_input("Number of frames", min_value=1, max_value=120, value=120)
resolution = st.selectbox("Resolution", ["256px", "768px"], index=0)
aspect_ratio = st.selectbox("Aspect Ratio", ["1:1", "16:9", "9:16"], index=0)
seed = st.number_input("Random Seed", min_value=0, value=42)
offload = st.checkbox("Enable CPU Offloading", value=True)
latitude = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=37.7749, step=0.0001)
longitude = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=-122.4194, step=0.0001)

if st.button("Generate Video"):
    try:
        response = requests.post(
            f"{VIDEO_GEN_ENDPOINT}/generate-video/",
            json={
                "prompt": prompt,
                "num_frames": num_frames,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "seed": seed,
                "offload": offload,
                "latitude": latitude,
                "longitude": longitude
            },
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        video_url = data.get("video_url")
        metadata = data.get("metadata")
        if video_url:
            st.write("Generated Video URL:", video_url)
            st.write("Metadata:", metadata)
            try:
                st.video(video_url)
            except Exception as e:
                st.warning("st.video failed, trying HTML video tag...")
                st.markdown(
                    f'<video width="320" height="240" controls><source src="{video_url}" type="video/mp4">Your browser does not support the video tag.</video>',
                    unsafe_allow_html=True
                )
            st.session_state["last_video_url"] = video_url
            st.session_state["last_metadata"] = metadata
        else:
            st.error("Video generation failed")
    except Exception as e:
        st.error(f"Error: {str(e)}")

# Ingestion
if "last_video_url" in st.session_state and st.button("Send to Ingestion"):
    try:
        response = requests.get(st.session_state["last_video_url"])
        response.raise_for_status()
        ingest_response = requests.post(
            INGESTION_ENDPOINT + "/ingest",
            files={"file": ("video.mp4", response.content, "video/mp4")},
            data={"timestamp": st.session_state["last_metadata"]["timestamp"]},
            timeout=10
        )
        ingest_response.raise_for_status()
        st.success("Video sent to ingestion")
    except Exception as e:
        st.error(f"Ingestion failed: {str(e)}")

# Real-Time Alerts
st.header("Real-Time Alerts")
try:
    response = minio_client.get_object(MINIO_BUCKET, "alerts/latest_sightings.json")
    alert_data = json.loads(response.read().decode())
    response.close()
    response.release_conn()

    st.write("### Alert Summary")
    st.write(alert_data.get("summary", "No summary available"))

    st.write("### Sighting Locations")
    m = folium.Map(location=[40.7128, -74.0060], zoom_start=10)
    for sighting in alert_data.get("metadata", {}).get("sightings", []):
        folium.Marker(
            location=[sighting["latitude"], sighting["longitude"]],
            popup=f"{sighting['object']} at {sighting['timestamp']}",
            icon=folium.Icon(color="red")
        ).add_to(m)
    folium_static(m)
except Exception as e:
    st.error(f"No alerts available: {str(e)}")
