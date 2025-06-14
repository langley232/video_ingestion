#file identifier storage/app.py
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
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
    access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "admin1234"),
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
FAISS_INDEX_PATH = os.getenv("FAISS_INDEX_PATH", "/app/faiss/video_index.faiss")
os.makedirs(os.path.dirname(FAISS_INDEX_PATH), exist_ok=True)
dimension = 512
res = faiss.StandardGpuResources()
faiss_index = faiss.IndexFlatL2(dimension)
gpu_index = faiss.index_cpu_to_gpu(res, 0, faiss_index)

if os.path.exists(FAISS_INDEX_PATH):
    cpu_index = faiss.read_index(FAISS_INDEX_PATH)
    gpu_index = faiss.index_cpu_to_gpu(res, 0, cpu_index)
    logger.info(f"Loaded FAISS index from {FAISS_INDEX_PATH}")

def get_video_embedding(frame):
    try:
        _, buffer = cv2.imencode('.jpg', frame)
        response = requests.post(
            'http://ollama:11434/api/embeddings',
            json={
                'model': 'nomic-embed-text:latest',
                'prompt': buffer.tobytes().hex()
            },
            timeout=10
        )
        response.raise_for_status()
        embedding = response.json().get('embedding', [])
        return np.array(embedding, dtype=np.float32) if embedding else None
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        return None

def store_video(video_content, metadata):
    try:
        video_binary = bytes.fromhex(video_content)
        timestamp = metadata["timestamp"].replace(" ", "_").replace(":", "-")
        object_name = f"videos/video_{timestamp}.mp4"
        minio_client.put_object(
            bucket_name, object_name, io.BytesIO(video_binary), len(video_binary),
            content_type="video/mp4"
        )
        logger.info(f"Video stored in MinIO at {object_name}")
        metadata_object_name = f"metadata/metadata_{timestamp}.json"
        metadata_json = json.dumps(metadata)
        minio_client.put_object(
            bucket_name, metadata_object_name, io.BytesIO(metadata_json.encode()), len(metadata_json),
            content_type="application/json"
        )
        logger.info(f"Metadata stored in MinIO at {metadata_object_name}")

        video_array = np.frombuffer(video_binary, dtype=np.uint8)
        video = cv2.imdecode(video_array, cv2.IMREAD_COLOR)
        if video is not None:
            embedding = get_video_embedding(video)
            if embedding is not None:
                gpu_index.add(np.array([embedding]))
                cpu_index = faiss.index_gpu_to_cpu(gpu_index)
                faiss.write_index(cpu_index, FAISS_INDEX_PATH)
                logger.info(f"Embedding stored in FAISS index at {FAISS_INDEX_PATH}")
            else:
                logger.warning("No embedding generated for video")
        else:
            logger.warning("Failed to decode video for embedding")

    except Exception as e:
        logger.error(f"Error storing video: {str(e)}")
        # Continue processing instead of raising

def main():
    max_retries = 10
    retry_delay = 10  # seconds
    topic = "video-ingestion"

    # Retry subscribing to the topic
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to subscribe to {topic} (Attempt {attempt + 1}/{max_retries})")
            consumer.subscribe([topic])
            logger.info(f"Successfully subscribed to {topic}")
            break
        except KafkaError as e:
            if e.code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
                logger.warning(f"Topic {topic} not found, retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Kafka error during subscription: {e}")
                time.sleep(retry_delay)
        except Exception as e:
            logger.error(f"Unexpected error during subscription: {e}")
            time.sleep(retry_delay)
    else:
        logger.error(f"Max retries reached, unable to subscribe to {topic}. Continuing to poll...")
        # Allow the service to continue running

    try:
        while True:
            try:
                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    logger.debug("No message received, continuing to poll...")
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.debug("Reached end of partition, continuing...")
                        continue
                    else:
                        logger.error(f"Kafka error: {msg.error()}")
                        continue

                try:
                    message = json.loads(msg.value().decode("utf-8"))
                    video_content = message.get("video_content")
                    if not video_content:
                        logger.warning("Received message with no video_content")
                        continue
                    store_video(video_content, message)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode message: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    continue

            except KafkaError as e:
                logger.error(f"Kafka error while polling: {e}")
                time.sleep(retry_delay)
            except Exception as e:
                logger.error(f"Unexpected error while polling: {e}")
                time.sleep(retry_delay)

    except KeyboardInterrupt:
        logger.info("Shutting down consumer...")
    finally:
        logger.info("Closing Kafka consumer...")
        consumer.close()

if __name__ == "__main__":
    main()
