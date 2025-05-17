import os
import uuid
import json
from fastapi import FastAPI, File, UploadFile, Form
from minio import Minio
from minio.error import S3Error
from confluent_kafka import Producer
import io

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
    print(f"Error creating bucket: {e}")

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
producer_config = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS
}
producer = Producer(producer_config)

def delivery_report(err, msg):
    if err is not None:
        print(f"Message delivery failed: {err}")
    else:
        print(f"Message delivered to {msg.topic()} [{msg.partition()}]")

@app.post("/ingest")
async def ingest_video(file: UploadFile = File(...), timestamp: str = Form(...)):
    # Read file content
    video_content = await file.read()

    # Store temporarily in MinIO
    object_name = f"videos/{uuid.uuid4()}.mp4"
    try:
        minio_client.put_object(
            bucket_name, object_name, io.BytesIO(video_content), len(video_content),
            content_type="video/mp4"
        )
    except S3Error as e:
        print(f"Error uploading to MinIO: {e}")
        raise

    # Send to Kafka
    message = {
        "video_content": video_content.hex(),
        "timestamp": timestamp,
        "minio_object_name": object_name
    }
    producer.produce("video-ingestion", json.dumps(message).encode("utf-8"), callback=delivery_report)
    producer.flush()

    return {"status": "Video ingested", "object_name": object_name}
