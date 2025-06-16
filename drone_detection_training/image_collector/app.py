from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import requests
import os
from minio import Minio
from minio.error import S3Error
import io
import json
import logging
from serp_api_client import SerpAPIClient
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Initialize MinIO client
minio_client = Minio(
    os.getenv("MINIO_ENDPOINT", "minio:9000"),
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
    secure=False
)

# Initialize SerpAPI client
serp_client = SerpAPIClient()

# Ensure bucket exists
BUCKET_NAME = "drone-training-data"
try:
    if not minio_client.bucket_exists(BUCKET_NAME):
        minio_client.make_bucket(BUCKET_NAME)
        logger.info(f"Created bucket: {BUCKET_NAME}")
except S3Error as e:
    logger.error(f"Error creating bucket: {str(e)}")
    raise


class ImageSearchRequest(BaseModel):
    query: str
    category: str
    num_images: Optional[int] = 100


class DatasetRequest(BaseModel):
    categories: Optional[List[str]] = None


@app.post("/collect-images")
async def collect_images(request: ImageSearchRequest):
    try:
        # Search for images
        images = serp_client.search_drone_images(
            request.query,
            request.category,
            request.num_images
        )

        # Download and store images
        stored_images = []
        for img in images:
            try:
                # Download image
                response = requests.get(img["url"], timeout=10)
                response.raise_for_status()

                # Generate unique filename
                filename = f"{request.category}/{img['title'].replace(' ', '_')}.jpg"

                # Store in MinIO
                minio_client.put_object(
                    BUCKET_NAME,
                    f"images/{filename}",
                    io.BytesIO(response.content),
                    len(response.content),
                    content_type="image/jpeg"
                )

                # Store metadata
                metadata_path = f"metadata/{filename}.json"
                minio_client.put_object(
                    BUCKET_NAME,
                    metadata_path,
                    io.BytesIO(json.dumps(img).encode()),
                    len(json.dumps(img).encode()),
                    content_type="application/json"
                )

                stored_images.append({
                    "filename": filename,
                    "metadata": img
                })

            except Exception as e:
                logger.error(f"Error storing image {img['url']}: {str(e)}")
                continue

        return {
            "status": "success",
            "stored_images": len(stored_images),
            "images": stored_images
        }

    except Exception as e:
        logger.error(f"Error collecting images: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/collect-dataset")
async def collect_dataset(request: DatasetRequest):
    try:
        # Collect all images
        all_images = serp_client.collect_training_dataset()

        # Filter by categories if specified
        if request.categories:
            all_images = [
                img for img in all_images
                if img["category"] in request.categories
            ]

        # Store dataset metadata
        dataset_metadata = {
            "total_images": len(all_images),
            "categories": list(set(img["category"] for img in all_images)),
            "collected_at": datetime.utcnow().isoformat()
        }

        minio_client.put_object(
            BUCKET_NAME,
            "dataset_metadata.json",
            io.BytesIO(json.dumps(dataset_metadata).encode()),
            len(json.dumps(dataset_metadata).encode()),
            content_type="application/json"
        )

        return {
            "status": "success",
            "dataset_metadata": dataset_metadata
        }

    except Exception as e:
        logger.error(f"Error collecting dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
