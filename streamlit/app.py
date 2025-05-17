import streamlit as st
import requests
import os
from minio import Minio
import faiss
import numpy as np
import cv2

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
        'http://ollama:11434/api/embeddings',
        json={
            'model': 'nomic-embed-text:latest',
            'prompt': cv2.imencode('.jpg', frame)[1].tobytes().hex()
        }
    )
    return np.array(response.json().get('embedding', []), dtype=np.float32)

def generate_video(prompt, num_frames):
    response = requests.post(
        "http://video_gen:8002/generate-video/",
        json={"prompt": prompt, "num_frames": num_frames}
    )
    if response.status_code == 200:
        return response.json().get("video_url")
    else:
        return None

st.title("Video Processing System")

# Video Generation Tab
st.header("Video Generation")
prompt = st.text_input("Enter video prompt")
num_frames = st.number_input("Number of frames", min_value=1, value=25)
if st.button("Generate Video"):
    video_url = generate_video(prompt, num_frames)
    if video_url:
        st.write("Generated Video URL:", video_url)  # Debug URL
        try:
            st.video(video_url)
        except Exception as e:
            st.warning("st.video failed, trying HTML video tag...")
            st.markdown(
                f'<video width="320" height="240" controls><source src="{video_url}" type="video/mp4">Your browser does not support the video tag.</video>',
                unsafe_allow_html=True
            )
        st.session_state["last_video_url"] = video_url
    else:
        st.error("Video generation failed")

# Ingestion
if "last_video_url" in st.session_state and st.button("Send to Ingestion"):
    response = requests.get(st.session_state["last_video_url"])
    if response.status_code == 200:
        ingest_response = requests.post(
            "http://ingestion:8000/ingest",
            files={"file": ("video.mp4", response.content, "video/mp4")},
            data={"timestamp": "2025-05-11 14:00:00"}
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
                # Fetch video from MinIO (assumes metadata stores object names)
                objects = list(minio_client.list_objects(bucket_name, prefix="videos/"))
                if idx < len(objects):
                    video_url = minio_client.presigned_get_object(bucket_name, objects[idx].object_name)
                    st.video(video_url)
