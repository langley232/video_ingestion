# file identifier ingestion/ingestion.py
import os
import uuid
import json
from fastapi import FastAPI, File, UploadFile, Form
from minio import Minio
from minio.error import S3Error
from kafka import KafkaProducer, KafkaAdminClient
from kafka.admin import NewTopic
from kafka.errors import TopicAlreadyExistsError
import io
import logging
from datetime import datetime
import cv2
import tempfile
import numpy as np
from ingestion.object_detection.detector import ObjectDetector
from ingestion.embedding_generator import EmbeddingGenerator
from PIL import Image

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# Initialize MinIO client
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
        logger.info(f"Created bucket: {bucket_name}")
except S3Error as e:
    logger.error(f"Error creating bucket: {str(e)}")

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
TOPIC_NAME = "video-ingestion"

# Initialize Kafka Admin Client
admin_client = KafkaAdminClient(bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS])

# Create Kafka topic if it doesn't exist
try:
    topic = NewTopic(
        name=TOPIC_NAME,
        num_partitions=1,
        replication_factor=1
    )
    admin_client.create_topics([topic])
    logger.info(f"Created Kafka topic: {TOPIC_NAME}")
except TopicAlreadyExistsError:
    logger.info(f"Kafka topic {TOPIC_NAME} already exists")
except Exception as e:
    logger.error(f"Error creating Kafka topic: {str(e)}")

# Initialize Kafka Producer
producer = KafkaProducer(
    bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
    value_serializer=lambda x: json.dumps(x).encode('utf-8')
)

# Initialize object detector and embedding generator
object_detector = ObjectDetector()
embedding_generator = EmbeddingGenerator()


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


def extract_frames(video_content: bytes, every_n_frames: int = 30):
    """Extract frames from video content every n frames."""
    frames = []
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
        temp_file.write(video_content)
        temp_file.flush()
        cap = cv2.VideoCapture(temp_file.name)
        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % every_n_frames == 0:
                frames.append((frame_count, frame.copy()))
            frame_count += 1
        cap.release()
        os.unlink(temp_file.name)
    return frames


@app.on_event("startup")
async def startup_event():
    pass


# Define suspicious objects for detection
SUSPICIOUS_OBJECT_TYPES = [
    "drone", "military drone", "unmanned aerial vehicle", "UAV",
    "quadcopter", "fixed-wing drone", "rotorcraft", "aircraft",
    "flying object", "airplane", "helicopter", "tank", "military vehicle",
    "soldier", "weapon", "missile"
]


@app.post("/ingest")
async def ingest_video(
    file: UploadFile = File(...),
    timestamp: str = Form(...),
    latitude: float = Form(40.7829),
    longitude: float = Form(-73.9654),
    location_name: str = Form("Central Park"),
    description: str = Form("")
):
    try:
        video_content = await file.read()
        ingestion_id = str(uuid.uuid4())
        video_metadata = extract_video_metadata(video_content)
        # Store video in MinIO
        video_path = f"generated_videos/{ingestion_id}.mp4"
        minio_client.put_object(
            bucket_name, video_path, io.BytesIO(
                video_content), len(video_content)
        )
        # Extract frames
        frames = extract_frames(video_content, every_n_frames=30)
        enriched_frames = []
        all_suspicious_objects = []

        for frame_number, frame in frames:
            # Scene embedding
            scene_embedding = embedding_generator.generate_embedding(frame)
            # Object detection
            detections = object_detector.detect_objects(frame)
            objects = []
            for det in detections:
                x1, y1, x2, y2 = map(int, det["bounding_box"])
                obj_crop = frame[y1:y2, x1:x2]
                obj_embedding = embedding_generator.generate_embedding(
                    obj_crop)
                
                object_data = {
                    "object_type": det["object_type"],
                    "confidence": det["confidence"],
                    "bounding_box": det["bounding_box"],
                    "object_embedding": obj_embedding.tolist()
                }
                objects.append(object_data)

                # Check if the object is suspicious
                if det["object_type"].lower() in SUSPICIOUS_OBJECT_TYPES:
                    all_suspicious_objects.append({
                        "frame_number": frame_number,
                        **object_data
                    })

            enriched_frames.append({
                "frame_number": frame_number,
                "scene_embedding": scene_embedding.tolist(),
                "objects": objects
            })
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
            "ingestion_time": datetime.utcnow().isoformat(),
            "video_path": video_path,
            "frames": enriched_frames
        }
        # Store metadata
        metadata_path = f"metadata/{ingestion_id}.json"
        metadata_bytes = json.dumps(metadata).encode('utf-8')
        minio_client.put_object(
            bucket_name, metadata_path, io.BytesIO(
                metadata_bytes), len(metadata_bytes)
        )
        # Send to Kafka
        message = {
            "video_path": video_path,
            "metadata_path": metadata_path,
            "timestamp": timestamp,
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "name": location_name
            },
            "enriched": True,
            "suspicious_objects_found": all_suspicious_objects
        }
        producer.send(TOPIC_NAME, value=message)
        producer.flush()
        return {
            "status": "Video ingested",
            "ingestion_id": ingestion_id,
            "video_path": video_path,
            "metadata_path": metadata_path
        }
    except Exception as e:
        logger.error(f"Error ingesting video: {str(e)}")
        raise


@app.get("/health")
async def health_check():
    return {"status": "ok"}
