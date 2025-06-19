# file identifier storage/app.py
import json
import os
import logging
from confluent_kafka import Consumer, KafkaError
import faiss
import numpy as np
import cv2
import requests
from minio import Minio
from minio.error import S3Error
import io
import time
from fastapi import FastAPI, HTTPException
import uvicorn
from threading import Thread

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# Global list to map FAISS internal IDs to ingestion_ids/metadata_paths
# WARNING: This is IN-MEMORY and NOT PERSISTED. Will reset on container restart.
# A proper solution requires persisting this mapping (e.g., in a DB, or a file)
# along with the FAISS index itself.
faiss_id_to_metadata_map = []


@app.post("/search")
async def search_videos(query_embedding: list):
    """Searches the FAISS index for similar video embeddings."""
    try:
        if not query_embedding:
            raise HTTPException(
                status_code=400, detail="No embedding provided")

        # Convert query embedding to numpy array
        query_vector = np.array([query_embedding], dtype=np.float32)

        # Search the FAISS index
        k = min(5, gpu_index.ntotal) # Number of results to return, cap at total elements
        if k == 0:
            logger.info("FAISS index is empty, returning no results.")
            return {"similar_videos": []}

        distances, indices = gpu_index.search(query_vector, k)

        # Get video paths and metadata from MinIO using the mapping
        results = []
        for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
            if idx != -1 and idx < len(faiss_id_to_metadata_map):  # Valid index within our map
                metadata_minio_path = faiss_id_to_metadata_map[idx]
                try:
                    # Get video metadata
                    metadata_obj = minio_client.get_object(
                        bucket_name, metadata_minio_path)
                    metadata = json.loads(metadata_obj.read().decode())
                    metadata_obj.close()
                    metadata_obj.release_conn()

                    results.append({
                        "video_path": metadata.get("video_path", ""),
                        "similarity": float(1 / (1 + distance)), # Convert distance to similarity score
                        "metadata": metadata
                    })
                except Exception as e:
                    logger.error(
                        f"Error retrieving metadata for index {idx} (path: {metadata_minio_path}): {str(e)}")
                    continue
            elif idx != -1:
                 logger.warning(f"FAISS index {idx} out of bounds for metadata map (len {len(faiss_id_to_metadata_map)}).")
        return {"similar_videos": results}
    except Exception as e:
        logger.error(f"Error searching videos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
consumer_config = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
    "group.id": "storage-group",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": True
}
consumer = Consumer(consumer_config)

# MinIO configuration
minio_client = Minio(
    endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000").replace("http://", ""),
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"), # Corrected
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"), # Corrected
    secure=False
)
bucket_name = os.getenv("MINIO_BUCKET", "videos")
try:
    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)
        logger.info(f"Created MinIO bucket: {bucket_name}")
except S3Error as e:
    logger.error(f"Error creating bucket: {e}")
    raise

# FAISS configuration
FAISS_INDEX_PATH = os.getenv(
    "FAISS_INDEX_PATH", "/app/faiss/video_index.faiss")
FAISS_MAP_PATH = os.path.join(os.path.dirname(FAISS_INDEX_PATH), "faiss_map.json") # Path for the mapping
os.makedirs(os.path.dirname(FAISS_INDEX_PATH), exist_ok=True)
dimension = 512 # Nomic-embed-text outputs 768 dimensions usually. Adjust if needed.
               # Check actual embedding dimension from Ollama.
               # If it's 768, change dimension = 768
               
res = faiss.StandardGpuResources()
faiss_index = faiss.IndexFlatL2(dimension)
gpu_index = faiss.index_cpu_to_gpu(res, 0, faiss_index)

# Load existing FAISS index and mapping on startup
if os.path.exists(FAISS_INDEX_PATH):
    try:
        cpu_index = faiss.read_index(FAISS_INDEX_PATH)
        gpu_index = faiss.index_cpu_to_gpu(res, 0, cpu_index)
        logger.info(f"Loaded FAISS index from {FAISS_INDEX_PATH}")
    except Exception as e:
        logger.error(f"Error loading FAISS index: {str(e)}. Starting with empty index.")
        # Re-initialize empty index if loading fails
        faiss_index = faiss.IndexFlatL2(dimension)
        gpu_index = faiss.index_cpu_to_gpu(res, 0, faiss_index)

if os.path.exists(FAISS_MAP_PATH):
    try:
        with open(FAISS_MAP_PATH, 'r') as f:
            faiss_id_to_metadata_map = json.load(f)
        logger.info(f"Loaded FAISS ID to metadata map from {FAISS_MAP_PATH}")
    except Exception as e:
        logger.error(f"Error loading FAISS map: {str(e)}. Starting with empty map.")
        faiss_id_to_metadata_map = []
else:
    logger.info("No existing FAISS ID to metadata map found, starting fresh.")


def get_video_embedding(frame: np.ndarray) -> np.ndarray:
    """Generates an embedding for a video frame using Ollama."""
    try:
        _, buffer = cv2.imencode('.jpg', frame)
        response = requests.post(
            f'{os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")}/api/embeddings', # Use env var or default
            json={
                'model': 'nomic-embed-text:latest',
                'prompt': buffer.tobytes().hex(), # Hex encode for binary image prompt
                'keep_alive': '5m' # Keep model loaded for a while
            },
            timeout=15 # Increased timeout
        )
        response.raise_for_status()
        embedding = response.json().get('embedding', [])
        return np.array(embedding, dtype=np.float32) if embedding else None
    except requests.exceptions.Timeout:
        logger.error("Ollama API request timed out during embedding generation.")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error generating embedding: {str(e)}. Response: {e.response.text if e.response else 'N/A'}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating embedding: {str(e)}")
        return None


def process_video_for_embedding_and_faiss(video_minio_path: str, metadata_minio_path: str):
    """Processes video from MinIO to generate embedding and add to FAISS."""
    try:
        logger.info(f"Processing video {video_minio_path} for embedding and FAISS storage.")

        # Get video content from MinIO
        response = minio_client.get_object(bucket_name, video_minio_path)
        video_binary = response.read()
        response.close()
        response.release_conn()
        logger.info(f"Retrieved video data for {video_minio_path} from MinIO.")

        # Decode video to extract a frame for embedding
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
            temp_file.write(video_binary)
            temp_file.flush()
            temp_path = temp_file.name

        cap = cv2.VideoCapture(temp_path)
        if not cap.isOpened():
            logger.warning(f"Failed to open video file {temp_path} for embedding. Skipping.")
            os.unlink(temp_path)
            return

        ret, frame = cap.read() # Read the first frame
        cap.release()
        os.unlink(temp_path) # Clean up temp file

        if ret:
            embedding = get_video_embedding(frame)
            if embedding is not None:
                # Add embedding to FAISS index
                current_faiss_size = gpu_index.ntotal
                gpu_index.add(np.array([embedding]))

                # Save FAISS index and update mapping
                cpu_index = faiss.index_gpu_to_cpu(gpu_index)
                faiss.write_index(cpu_index, FAISS_INDEX_PATH)

                # Store mapping: current FAISS ID (which is current_faiss_size) to metadata_minio_path
                # Ensure faiss_id_to_metadata_map is grown if needed
                if len(faiss_id_to_metadata_map) <= current_faiss_size:
                    # Pad with Nones if necessary, then append
                    faiss_id_to_metadata_map.extend([None] * (current_faiss_size + 1 - len(faiss_id_to_metadata_map)))
                faiss_id_to_metadata_map[current_faiss_size] = metadata_minio_path
                
                # Persist the mapping
                with open(FAISS_MAP_PATH, 'w') as f:
                    json.dump(faiss_id_to_metadata_map, f)

                logger.info(f"Embedding added to FAISS index (ID: {current_faiss_size}). Index and map saved.")
            else:
                logger.warning("No embedding generated for video, not added to FAISS.")
        else:
            logger.warning(f"Failed to extract frame from {video_minio_path} for embedding.")

    except Exception as e:
        logger.error(f"Error processing video for embedding/FAISS: {str(e)}")


def kafka_consumer_loop():
    """Main loop for consuming Kafka messages and triggering video embedding."""
    logger.info("Starting Kafka consumer loop for storage service...")
    max_retries = 10
    retry_delay = 10
    
    # Initial subscription attempt with retries
    for attempt in range(max_retries):
        try:
            consumer.subscribe([TOPIC_NAME])
            logger.info(f"Successfully subscribed to {TOPIC_NAME}")
            break
        except Exception as e:
            logger.error(f"Kafka subscription failed (Attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error(f"Max retries reached for Kafka subscription. Consumer might not receive messages.")
                # Continue without subscribing, rely on subsequent polls to implicitly re-subscribe
                pass 

    try:
        while True:
            msg = consumer.poll(1000) # Poll for messages

            if msg is None:
                logger.debug("No message received, continuing to poll...")
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    logger.debug("Reached end of partition, continuing...")
                    continue
                else:
                    logger.error(f"Kafka consumer error: {msg.error()}")
                    continue

            try:
                message_value = msg.value # Already deserialized by value_deserializer
                video_path = message_value.get("video_path")
                metadata_path = message_value.get("metadata_path") # Get metadata path from message

                if video_path and metadata_path:
                    process_video_for_embedding_and_faiss(video_path, metadata_path)
                else:
                    logger.warning("Received message with missing video_path or metadata_path")

            except Exception as e:
                logger.error(f"Error processing Kafka message in storage consumer: {str(e)}")
                # Continue to next message, don't crash loop

    except KeyboardInterrupt:
        logger.info("Shutting down storage consumer...")
    finally:
        logger.info("Closing Kafka consumer for storage...")
        consumer.close()


# Start Kafka consumer in a separate thread
consumer_thread = Thread(target=kafka_consumer_loop)
consumer_thread.daemon = True
consumer_thread.start()


if __name__ == "__main__":
    # Start FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=8001)
