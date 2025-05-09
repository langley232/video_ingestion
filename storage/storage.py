import json
import os
import binascii
import logging
from confluent_kafka import Consumer, KafkaError
import faiss
import numpy as np
import cv2
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
consumer_config = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
    "group.id": "storage-group",
    "auto.offset.reset": "earliest"
}
consumer = Consumer(consumer_config)
consumer.subscribe(["video-ingestion"])

# Local storage configuration
LOCAL_STORAGE_PATH = os.getenv("LOCAL_STORAGE_PATH", "/app/videos")
os.makedirs(LOCAL_STORAGE_PATH, exist_ok=True)

# FAISS configuration
FAISS_INDEX_PATH = os.getenv("FAISS_INDEX_PATH", "/app/faiss/video_index.faiss")
os.makedirs(os.path.dirname(FAISS_INDEX_PATH), exist_ok=True)
dimension = 512  # Adjust based on MiniCPM-V 2.6 embedding size
faiss_index = faiss.IndexFlatL2(dimension)
if os.path.exists(FAISS_INDEX_PATH):
    faiss_index = faiss.read_index(FAISS_INDEX_PATH)

def get_video_embedding(frame):
    """Generate embedding for a video frame using MiniCPM-V 2.6 via Ollama."""
    try:
        _, buffer = cv2.imencode('.jpg', frame)
        response = requests.post(
            'http://ollama:11434/api/generate',
            json={
                'model': 'minicpm-v:2.6',
                'prompt': 'Generate embedding for this image.',
                'image': buffer.tobytes().hex()
            }
        )
        response.raise_for_status()
        embedding = response.json().get('embedding', [])
        return np.array(embedding, dtype=np.float32) if embedding else None
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        return None

def store_video(video_content, metadata):
    """Store video and its metadata locally."""
    try:
        # Convert hex back to binary
        video_binary = binascii.unhexlify(video_content)

        # Generate storage path
        timestamp = metadata["timestamp"].replace(" ", "_").replace(":", "-")
        filename = f"video_{timestamp}.mp4"
        storage_path = os.path.join(LOCAL_STORAGE_PATH, filename)

        # Store video locally
        with open(storage_path, "wb") as f:
            f.write(video_binary)
        logger.info(f"Video stored at {storage_path}")

        # Store metadata in a JSON file
        metadata_path = os.path.join(LOCAL_STORAGE_PATH, f"metadata_{timestamp}.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)
        logger.info(f"Metadata stored at {metadata_path}")

        # Generate and store embedding
        video_array = np.frombuffer(video_binary, dtype=np.uint8)
        video = cv2.imdecode(video_array, cv2.IMREAD_COLOR)
        if video is not None:
            embedding = get_video_embedding(video)
            if embedding is not None:
                faiss_index.add(np.array([embedding]))
                faiss.write_index(faiss_index, FAISS_INDEX_PATH)
                logger.info(f"Embedding stored in FAISS index at {FAISS_INDEX_PATH}")

    except Exception as e:
        logger.error(f"Error storing video: {str(e)}")
        raise

def main():
    """Consume messages from Kafka and process them."""
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

            # Process message
            message = json.loads(msg.value().decode("utf-8"))
            video_content = message["video_content"]
            metadata = message
            store_video(video_content, metadata)

    finally:
        consumer.close()

if __name__ == "__main__":
    main()
