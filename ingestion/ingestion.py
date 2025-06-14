# file identifier ingestion/ingestion.py
import os
import uuid
import json
from fastapi import FastAPI, File, UploadFile, Form
from minio import Minio
from minio.error import S3Error
from confluent_kafka import Producer, AdminClient
import io
import logging
from datetime import datetime
import cv2
import tempfile

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Initialize MinIO client
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
except S3Error as e:
    logger.error(f"Error creating bucket: {e}")

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
TOPIC_NAME = "video-ingestion"

# Initialize Kafka Admin Client
admin_config = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS
}
admin_client = AdminClient(admin_config)

# Create Kafka topic if it doesn't exist


def create_kafka_topic():
    try:
        metadata = admin_client.list_topics(timeout=10)
        if TOPIC_NAME not in metadata.topics:
            logger.info(f"Creating Kafka topic: {TOPIC_NAME}")
            admin_client.create_topics([
                {
                    "topic": TOPIC_NAME,
                    "num_partitions": 1,
                    "replication_factor": 1
                }
            ])
            logger.info(f"Successfully created topic: {TOPIC_NAME}")
        else:
            logger.info(f"Topic {TOPIC_NAME} already exists")
    except Exception as e:
        logger.error(f"Error creating Kafka topic: {e}")
        raise


# Initialize Kafka Producer
producer_config = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS
}
producer = Producer(producer_config)


def delivery_report(err, msg):
    if err is not None:
        logger.error(f"Message delivery failed: {err}")
    else:
        logger.info(f"Message delivered to {msg.topic()} [{msg.partition()}]")


def extract_video_metadata(video_content: bytes) -> dict:
    """Extract metadata from video content."""
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
        temp_file.write(video_content)
        temp_file.flush()

        cap = cv2.VideoCapture(temp_file.name)
        if not cap.isOpened():
            return {}

        # Get video properties
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0

        cap.release()
        os.unlink(temp_file.name)

        return {
            "width": width,
            "height": height,
            "fps": fps,
            "frame_count": frame_count,
            "duration": duration
        }


@app.on_event("startup")
async def startup_event():
    create_kafka_topic()


@app.post("/ingest")
async def ingest_video(
    file: UploadFile = File(...),
    timestamp: str = Form(...),
    latitude: float = Form(40.7829),  # Default to Central Park
    longitude: float = Form(-73.9654),  # Default to Central Park
    location_name: str = Form("Central Park"),  # Default location name
    description: str = Form("")
):
    # Read file content
    video_content = await file.read()

    # Generate unique ID for this ingestion
    ingestion_id = str(uuid.uuid4())

    # Extract video metadata
    video_metadata = extract_video_metadata(video_content)

    # Create metadata object
    metadata = {
        "ingestion_id": ingestion_id,
        "original_filename": file.filename,
        "content_type": file.content_type,
        "timestamp": timestamp,
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "name": location_name
        },
        "description": description,
        "video_metadata": video_metadata,
        "ingestion_time": datetime.utcnow().isoformat()
    }

    # Store video in MinIO
    video_path = f"generated_videos/{ingestion_id}.mp4"
    try:
        minio_client.put_object(
            bucket_name, video_path, io.BytesIO(
                video_content), len(video_content),
            content_type="video/mp4"
        )

        # Store metadata
        metadata_path = f"metadata/{ingestion_id}.json"
        minio_client.put_object(
            bucket_name, metadata_path,
            io.BytesIO(json.dumps(metadata).encode('utf-8')),
            len(json.dumps(metadata).encode('utf-8')),
            content_type="application/json"
        )
    except S3Error as e:
        logger.error(f"Error uploading to MinIO: {e}")
        raise

    # Send to Kafka
    message = {
        "video_path": video_path,
        "metadata_path": metadata_path,
        "timestamp": timestamp,
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "name": location_name
        }
    }
    producer.produce(TOPIC_NAME, json.dumps(
        message).encode("utf-8"), callback=delivery_report)
    producer.flush()

    return {
        "status": "Video ingested",
        "ingestion_id": ingestion_id,
        "video_path": video_path,
        "metadata_path": metadata_path
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}
