from confluent_kafka import Consumer, KafkaError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import json
import numpy as np
import cv2
import requests
import os
import logging
import threading
import faiss
import glob
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Validate environment variables
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
FAISS_INDEX_PATH = os.getenv('FAISS_INDEX_PATH', '/app/faiss/video_index.faiss')
LOCAL_STORAGE_PATH = os.getenv('LOCAL_STORAGE_PATH', '/app/videos')

# Kafka configuration
kafka_config = {
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'group.id': 'alert-consumer-group',
    'auto.offset.reset': 'earliest'
}
consumer = Consumer(kafka_config)
consumer.subscribe(['video-ingestion'])

# FAISS configuration
dimension = 512  # Adjust based on MiniCPM-V 2.6 embedding size

def detect_objects(frame):
    """Detect objects in a frame using MiniCPM-V 2.6 via Ollama."""
    try:
        _, buffer = cv2.imencode('.jpg', frame)
        response = requests.post(
            'http://ollama:11434/api/generate',
            json={
                'model': 'minicpm-v:2.6',
                'prompt': 'Detect objects in this image (e.g., tank, military vehicle, missile, drone, person).',
                'image': buffer.tobytes().hex()
            }
        )
        response.raise_for_status()
        objects = response.json().get('objects', [])
        return objects if objects else []
    except Exception as e:
        logger.error(f"Error detecting objects: {str(e)}")
        return []

def generate_response(prompt, objects=None):
    """Generate a response using MiniCPM-V 2.6 via Ollama."""
    try:
        response = requests.post(
            'http://ollama:11434/api/generate',
            json={
                'model': 'minicpm-v:2.6',
                'prompt': prompt or f"Generate alert for detected objects: {objects}"
            }
        )
        response.raise_for_status()
        return response.json().get('text', 'No response generated')
    except Exception as e:
        logger.error(f"Error generating response: {str(e)}")
        return "Error generating response"

def get_query_embedding(object_type):
    """Generate an embedding for the query object type (placeholder)."""
    try:
        response = requests.post(
            'http://ollama:11434/api/generate',
            json={
                'model': 'minicpm-v:2.6',
                'prompt': f"Generate embedding for object type: {object_type}"
            }
        )
        response.raise_for_status()
        embedding = response.json().get('embedding', [])
        return np.array(embedding, dtype=np.float32) if embedding else np.random.randn(dimension).astype(np.float32)
    except Exception as e:
        logger.error(f"Error generating query embedding: {str(e)}")
        return np.random.randn(dimension).astype(np.float32)

def query_vector_store(start_time, end_time, object_type):
    """Query FAISS and local metadata for videos matching date/time range and object type."""
    try:
        # Parse timestamps
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")

        # Query FAISS vector store
        if not os.path.exists(FAISS_INDEX_PATH):
            return generate_response(f"No FAISS index found at {FAISS_INDEX_PATH}")
        faiss_index = faiss.read_index(FAISS_INDEX_PATH)
        query_embedding = get_query_embedding(object_type).reshape(1, -1)
        _, indices = faiss_index.search(query_embedding, k=10)
        if not indices[0].size:
            return generate_response("No matching vectors found in FAISS")

        # Load metadata from JSON files within the date/time range
        results = []
        metadata_files = glob.glob(os.path.join(LOCAL_STORAGE_PATH, "metadata_*.json"))
        for metadata_file in metadata_files:
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
                file_timestamp = datetime.strptime(metadata['timestamp'], "%Y-%m-%d %H:%M:%S")
                if start_dt <= file_timestamp <= end_dt and object_type.lower() in [obj.lower() for obj in metadata['objects']]:
                    results.append(metadata)

        prompt = f"Found {len(results)} video frames matching {object_type} from {start_time} to {end_time}"
        return generate_response(prompt)
    except Exception as e:
        logger.error(f"Error querying vector store: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def process_alerts():
    """Process Kafka messages for real-time alerts."""
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    logger.error(f"Kafka error: {msg.error()}")
                    break
            data = json.loads(msg.value().decode('utf-8'))
            frame_hex = data['video_content']
            frame_data = bytes.fromhex(frame_hex)
            frame_array = np.frombuffer(frame_data, dtype=np.uint8)
            frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
            if frame is None:
                logger.warning("Failed to decode frame")
                continue
            objects = detect_objects(frame)
            if objects:
                response = generate_response(None, objects)
                logger.info(f"Alert: {response}")
    except Exception as e:
        logger.error(f"Error in alert processing: {str(e)}")
    finally:
        consumer.close()

class Query(BaseModel):
    start_time: str
    end_time: str
    object_type: str

@app.post("/query/")
async def query_endpoint(query: Query):
    result = query_vector_store(
        query.start_time,
        query.end_time,
        query.object_type
    )
    return {"result": result}

@app.on_event("startup")
async def startup_event():
    alert_thread = threading.Thread(target=process_alerts, daemon=True)
    alert_thread.start()
    logger.info("Started alert processing thread")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
