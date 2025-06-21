# file identifier storage/app.py
import json
import os
import logging
from confluent_kafka import Consumer, KafkaError
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
import tempfile
from storage.mongodb_client import MongoDBAtlasClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()


@app.get("/health")
async def health_check():
    return {"status": "ok"}

# MongoDB Atlas client
mongodb_client = MongoDBAtlasClient()

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
consumer_config = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
    "group.id": "storage-group",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": "true"
}
consumer = Consumer(consumer_config)

# MinIO configuration
minio_client = Minio(
    endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000").replace("http://", ""),
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
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


@app.post("/search")
async def search_videos(query_embedding: list, filters: dict = None):
    try:
        results = mongodb_client.vector_search(query_embedding, filters)
        return {"similar_videos": results}
    except Exception as e:
        logger.error(f"Error searching videos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def process_metadata_from_minio(metadata_minio_path: str):
    try:
        metadata_obj = minio_client.get_object(
            bucket_name, metadata_minio_path)
        metadata = json.loads(metadata_obj.read().decode())
        metadata_obj.close()
        metadata_obj.release_conn()
        # Insert into MongoDB Atlas
        mongodb_client.insert_frame(metadata)
        logger.info(
            f"Inserted metadata for {metadata_minio_path} into MongoDB Atlas.")
    except Exception as e:
        logger.error(f"Error processing metadata from MinIO: {str(e)}")


def kafka_consumer_loop():
    logger.info("Starting Kafka consumer loop for storage service...")
    max_retries = 10
    retry_delay = 10
    TOPIC_NAME = "video-ingestion"
    for attempt in range(max_retries):
        try:
            consumer.subscribe([TOPIC_NAME])
            logger.info(f"Successfully subscribed to {TOPIC_NAME}")
            break
        except Exception as e:
            logger.error(
                f"Kafka subscription failed (Attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error(
                    f"Max retries reached for Kafka subscription. Consumer might not receive messages.")
                pass
    try:
        while True:
            msg = consumer.poll(1000)
            if msg is None:
                continue
            if msg.error() is not None:
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    logger.error(f"Kafka consumer error: {msg.error()}")
                    continue
            try:
                message_value = json.loads(msg.value().decode("utf-8"))
                metadata_path = message_value.get("metadata_path")
                if metadata_path:
                    process_metadata_from_minio(metadata_path)
                else:
                    logger.warning(
                        "Received message with missing metadata_path")
            except Exception as e:
                logger.error(
                    f"Error processing Kafka message in storage consumer: {str(e)}")
                continue
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
    uvicorn.run(app, host="0.0.0.0", port=8001)
