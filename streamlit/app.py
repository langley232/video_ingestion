import streamlit as st
import requests
import json
import asyncio
import websockets
from datetime import datetime

# Streamlit app configuration
st.set_page_config(page_title="Video Processing App", layout="wide")

# WebSocket for real-time alerts
alerts = []
async def alert_listener():
    async with websockets.connect("ws://localhost:8501/alert") as websocket:
        while True:
            message = await websocket.recv()
            alert_data = json.loads(message)
            alerts.append(alert_data)
            st.rerun()

if "alert_task" not in st.session_state:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    st.session_state["alert_task"] = loop.create_task(alert_listener())

# Define tabs
tab1, tab2, tab3 = st.tabs(["Query", "Video Generation", "Real-Time Alerts"])

# Tab 1: Query
with tab1:
    st.header("Query Videos")
    start_time = st.text_input("Start Time (YYYY-MM-DD HH:MM:SS)", "2025-05-06 00:00:00")
    end_time = st.text_input("End Time (YYYY-MM-DD HH:MM:SS)", "2025-05-06 23:59:59")
    object_type = st.selectbox("Object Type", ["tank", "military vehicle", "missile", "drone", "person"])
    if st.button("Search"):
        if start_time and end_time and object_type:
            try:
                response = requests.post("http://query_alert:8001/query/", json={
                    "start_time": start_time,
                    "end_time": end_time,
                    "object_type": object_type
                })
                response.raise_for_status()
                result = response.json().get("result", "No results found.")
                st.write("Search Results:")
                st.write(result)
            except requests.exceptions.RequestException as e:
                st.error(f"Error querying videos: {e}")

# Tab 2: Video Generation
with tab2:
    st.header("Generate and Ingest Video")
    prompt = st.text_input("Enter a prompt for video generation:", "A military tank is coming through the road in front of 20 Ethan Allen DR Acton, MA 01720")
    image_file = st.file_uploader("Upload an image (optional)", type=["jpg", "png"])

    # Generate video
    if st.button("Generate Video"):
        if prompt:
            try:
                files = {"image_path": image_file} if image_file else None
                response = requests.post(
                    "http://video_gen:8002/generate",
                    data={"prompt": prompt},
                    files=files if files else None
                )
                response.raise_for_status()
                video_content = response.content
                st.session_state["generated_video"] = video_content
                st.session_state["video_prompt"] = prompt
                st.video(video_content)
                st.success("Video generated successfully!")
            except requests.exceptions.RequestException as e:
                st.error(f"Error generating video: {e}")
        else:
            st.warning("Please enter a prompt.")

    # Ingest video with metadata
    if "generated_video" in st.session_state:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        st.write(f"Generated Video Timestamp: {timestamp}")
        if st.button("Send to Ingestion"):
            try:
                files = {"file": ("generated_video.mp4", st.session_state["generated_video"], "video/mp4")}
                data = {"timestamp": timestamp}
                response = requests.post("http://ingestion:8000/ingest", files=files, data=data)
                response.raise_for_status()
                st.success("Video sent to ingestion successfully!")
            except requests.exceptions.RequestException as e:
                st.error(f"Error sending video to ingestion: {e}")

# Tab 3: Real-Time Alerts
with tab3:
    st.header("Real-Time Alerts")
    if alerts:
        for alert in alerts[-5:]:  # Show last 5 alerts
            st.subheader(f"Alert at {alert['timestamp']}")
            st.write(f"Objects Detected: {', '.join(alert['objects'])}")
            st.write(f"Geolocation: {alert['geolocation']}")
            video_bytes = bytes.fromhex(alert['video_content'])
            st.video(video_bytes)
    else:
        st.write("No real-time alerts yet.")
        
