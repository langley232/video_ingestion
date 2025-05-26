import streamlit as st
import requests
import os
from minio import Minio
import faiss
import numpy as np
import cv2
from datetime import datetime

# Initialize MinIO client
minio_client = Minio(
    os.getenv("MINIO_ENDPOINT", "minio:9000").replace("http://", ""),
    access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "admin1234"),
    secure=False
)
bucket_name = os.getenv("MINIO_BUCKET", "videos")

# Initialize FAISS index
FAISS_INDEX_PATH = "/app/faiss/video_index.faiss"
dimension = 512
faiss_index = faiss.IndexFlatL2(dimension)
if os.path.exists(FAISS_INDEX_PATH):
    faiss_index = faiss.read_index(FAISS_INDEX_PATH)

def get_embedding(frame):
    response = requests.post(
        os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434/api/embeddings"),
        json={
            'model': 'nomic-embed-text:latest',
            'prompt': cv2.imencode('.jpg', frame)[1].tobytes().hex()
        }
    )
    return np.array(response.json().get('embedding', []), dtype=np.float32)

def generate_video(prompt, num_frames, resolution, aspect_ratio, seed, offload, latitude=None, longitude=None):
    response = requests.post(
        os.getenv("VIDEO_GEN_ENDPOINT", "http://open_sora_service:8000/generate-video/"),
        json={
            "prompt": prompt,
            "num_frames": num_frames,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "seed": seed,
            "offload": offload,
            "latitude": latitude,
            "longitude": longitude
        }
    )
    if response.status_code == 200:
        return response.json().get("video_url"), response.json().get("metadata")
    else:
        return None, None

st.title("Video Processing System")

# Video Generation Tab
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
    video_url, metadata = generate_video(prompt, num_frames, resolution, aspect_ratio, seed, offload, latitude, longitude)
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

# Ingestion
if "last_video_url" in st.session_state and st.button("Send to Ingestion"):
    response = requests.get(st.session_state["last_video_url"])
    if response.status_code == 200:
        ingest_response = requests.post(
            os.getenv("INGESTION_ENDPOINT", "http://ingestion:8000/ingest"),
            files={"file": ("video.mp4", response.content, "video/mp4")},
            data={"timestamp": st.session_state["last_metadata"]["timestamp"]}
        )
        if ingest_response.status_code == 200:
            st.success("Video sent to ingestion")
        else:
            st.error("Ingestion failed")
    else:
        st.error("Failed to fetch video")

# Real-Time Alerts (Placeholder)
st.header("Real-Time Alerts")
if "alerts" not in st.session_state:
    st.session_state["alerts"] = []
for alert in st.session_state["alerts"]:
    st.write(alert)

# Similar Videos Query
st.header("Find Similar Videos")
query_image = st.file_uploader("Upload an image to find similar videos", type=["jpg", "png"])
if query_image and st.button("Search"):
    img_array = np.frombuffer(query_image.read(), np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    embedding = get_embedding(img)
    if embedding is not None:
        D, I = faiss_index.search(np.array([embedding]), k=5)
        for idx in I[0]:
            if idx >= 0:
                objects = list(minio_client.list_objects(bucket_name, prefix="videos/"))
                if idx < len(objects):
                    video_url = minio_client.presigned_get_object(bucket_name, objects[idx].object_name)
                    st.video(video_url)
