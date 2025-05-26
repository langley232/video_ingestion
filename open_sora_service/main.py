import os
import logging
import tempfile
import subprocess
import shutil
import uuid
from datetime import datetime, timedelta
import json
import random

from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
from minio import Minio
from minio.error import S3Error

# 1. FastAPI Setup & Logging
app = FastAPI(title="Open-Sora Video Generation Service")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 2. MinIO Integration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin1234")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")
MINIO_SECURE = os.getenv("MINIO_SECURE", "False").lower() == "true"

try:
    minio_client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )
    found = minio_client.bucket_exists(MINIO_BUCKET)
    if not found:
        minio_client.make_bucket(MINIO_BUCKET)
        logger.info(f"MinIO bucket '{MINIO_BUCKET}' created.")
    else:
        logger.info(f"MinIO bucket '{MINIO_BUCKET}' already exists.")
except Exception as e:
    logger.error(f"Error initializing MinIO client or ensuring bucket exists: {e}")
    minio_client = None

# 3. Request Model (VideoRequest)
class VideoRequest(BaseModel):
    prompt: str
    num_frames: int = Field(default=120, description="Number of frames to generate (120 for 5 seconds at 24 FPS)")
    resolution: str = Field(default="256px", pattern="^(256px|768px)$", description="Resolution of the video")
    aspect_ratio: str = Field(default="1:1", pattern="^(\d+:\d+)$", description="Aspect ratio (e.g., 16:9, 1:1, 9:16)")
    model_path: str = Field(default="/app/open-sora-model-cache/Open-Sora-v2", description="Path to the Open-Sora model directory")
    opensora_repo_path: str = Field(default="/app/open-sora", description="Path to the cloned Open-Sora repository")
    seed: int = Field(default=42, description="Random seed for generation")
    offload: bool = Field(default=True, description="Whether to use CPU offloading")
    latitude: float = Field(default=None, description="Latitude of the video location", allow_none=True)
    longitude: float = Field(default=None, description="Longitude of the video location", allow_none=True)

# 4. API Endpoint (/generate-video/)
@app.post("/generate-video/")
async def generate_video(request: VideoRequest = Body(...)):
    if not minio_client:
        raise HTTPException(status_code=503, detail="MinIO client not initialized. Check server logs.")

    temp_output_dir = None
    try:
        temp_output_dir = tempfile.mkdtemp(prefix="opensora_")
        logger.info(f"Created temporary output directory: {temp_output_dir}")

        if request.resolution == "256px":
            config_file_name = "t2i2v_256px.py"
        elif request.resolution == "768px":
            config_file_name = "t2i2v_768px.py"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported resolution: {request.resolution}")

        config_path = os.path.join(request.opensora_repo_path, "configs/diffusion/inference", config_file_name)
        inference_script_path = os.path.join(request.opensora_repo_path, "scripts/diffusion/inference.py")

        if not os.path.exists(request.opensora_repo_path):
            raise HTTPException(status_code=500, detail=f"Open-Sora repo path not found: {request.opensora_repo_path}")
        if not os.path.exists(inference_script_path):
            raise HTTPException(status_code=500, detail=f"Open-Sora inference script not found: {inference_script_path}")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=500, detail=f"Open-Sora config file not found: {config_path}")
        if not os.path.exists(request.model_path):
            raise HTTPException(status_code=500, detail=f"Model path not found: {request.model_path}")

        command = [
            "torchrun",
            "--nproc_per_node", "1",
            "--standalone",
            inference_script_path,
            config_path,
            "--model-path", request.model_path,
            "--prompt", request.prompt,
            "--num-frames", str(request.num_frames),
            "--aspect_ratio", request.aspect_ratio,
            "--save-dir", temp_output_dir,
            "--sampling_option.seed", str(request.seed),
        ]
        if request.offload:
            command.append("--offload")

        logger.info(f"Executing Open-Sora command: {' '.join(command)}")
        process = subprocess.run(command, capture_output=True, text=True, check=False)

        if process.returncode != 0:
            logger.error(f"Open-Sora execution failed. Return code: {process.returncode}")
            logger.error(f"Stdout: {process.stdout}")
            logger.error(f"Stderr: {process.stderr}")
            raise HTTPException(status_code=500, detail=f"Video generation failed. Error: {process.stderr[:500]}")

        video_file_path = None
        for root, dirs, files in os.walk(temp_output_dir):
            for file in files:
                if file.endswith(".mp4"):
                    video_file_path = os.path.join(root, file)
                    logger.info(f"Found generated video: {video_file_path}")
                    break
            if video_file_path:
                break

        if not video_file_path:
            raise HTTPException(status_code=500, detail="Video generation completed but output .mp4 file not found.")

        # Generate dynamic metadata
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lat = request.latitude if request.latitude is not None else random.uniform(-90, 90)
        lon = request.longitude if request.longitude is not None else random.uniform(-180, 180)
        metadata = {
            "prompt": request.prompt,
            "timestamp": timestamp,
            "latitude": lat,
            "longitude": lon,
            "num_frames": request.num_frames,
            "resolution": request.resolution,
            "aspect_ratio": request.aspect_ratio,
            "seed": request.seed
        }

        # Upload video to MinIO
        sanitized_prompt_prefix = "".join(filter(str.isalnum, request.prompt.lower().split()[:3]))[:50]
        unique_id = uuid.uuid4()
        object_name = f"generated_videos/{unique_id}_{sanitized_prompt_prefix}.mp4"
        try:
            minio_client.fput_object(
                MINIO_BUCKET,
                object_name,
                video_file_path,
                content_type="video/mp4"
            )
            logger.info(f"Successfully uploaded video to MinIO: {object_name}")

            # Upload metadata to MinIO
            metadata_object_name = f"metadata/{unique_id}_{sanitized_prompt_prefix}.json"
            with open("/tmp/metadata.json", "w") as f:
                json.dump(metadata, f)
            minio_client.fput_object(
                MINIO_BUCKET,
                metadata_object_name,
                "/tmp/metadata.json",
                content_type="application/json"
            )
            logger.info(f"Successfully uploaded metadata to MinIO: {metadata_object_name}")

            presigned_url = minio_client.presigned_get_object(
                MINIO_BUCKET,
                object_name,
                expires=timedelta(days=7)
            )
            logger.info(f"Generated presigned URL: {presigned_url}")

        except S3Error as s3_err:
            logger.error(f"MinIO S3 Error during upload or URL generation: {s3_err}")
            raise HTTPException(status_code=500, detail=f"MinIO error: {s3_err}")

        return {"status": "success", "video_url": presigned_url, "object_name": object_name, "metadata": metadata}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("An unexpected error occurred in /generate-video/ endpoint")
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {e}")
    finally:
        if temp_output_dir and os.path.exists(temp_output_dir):
            try:
                shutil.rmtree(temp_output_dir)
                logger.info(f"Successfully removed temporary directory: {temp_output_dir}")
            except Exception as e:
                logger.error(f"Error removing temporary directory {temp_output_dir}: {e}")

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok"}
