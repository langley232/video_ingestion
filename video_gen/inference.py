import tempfile
import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
import os
from minio import Minio
from diffusers import DiffusionPipeline, DPMScheduler
import torch
from minio.error import S3Error

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define FastAPI app
app = FastAPI()

# Initialize MinIO client
minio_client = Minio(
    os.getenv("MINIO_ENDPOINT", "minio:9000").replace("http://", ""),
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
    raise  # Important:  Raise the exception to prevent the app from running with a misconfigured bucket.

# Load the model from pre-downloaded path
try:
    model_path = "/app/cache/huggingface/models/Wan-AI/Wan2.1-T2V-1.3B-Diffusers" # Corrected path to match download_model.sh
    pipe = DiffusionPipeline.from_pretrained(
        model_path,
        torch_dtype=torch.float16,
        use_safetensors=True,
        low_cpu_mem_usage=True
    )
    if torch.cuda.is_available():
        pipe = pipe.to("cuda")
        pipe.enable_model_cpu_offload()  # Optimize memory usage
    pipe.scheduler = DPMScheduler.from_config(pipe.scheduler.config) # add scheduler.
    logger.info("Wan 2.1 T2V-1.3B model loaded successfully")
except Exception as e:
    logger.error(f"Failed to load Wan 2.1 T2V-1.3B model: {str(e)}")
    raise  #  Important:  Raise the exception if the model fails to load

# Define request model
class VideoRequest(BaseModel):
    prompt: str
    num_frames: int



@app.post("/generate-video/")
async def generate_video(request: VideoRequest):
    try:
        prompt = request.prompt
        num_frames = request.num_frames

        if num_frames <= 0:
            raise HTTPException(status_code=400, detail="Number of frames must be positive")
        if num_frames > 100:
            raise HTTPException(status_code=400, detail="Number of frames cannot exceed 100")

        # Generate frames - Corrected height to be even
        frames = pipe(
            prompt=prompt,
            num_frames=num_frames,
            height=256,  # Ensure height is even
            width=256,
            num_inference_steps=50,
        ).frames


        # Create a temporary file for the video
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            video_path = temp_file.name
            frame_rate = 24
            frame_size = (256, 256)
            video_writer = cv2.VideoWriter(
                video_path,
                cv2.VideoWriter_fourcc(*"mp4v"),
                frame_rate,
                frame_size
            )
            for frame in frames:
                frame = (frame * 255).astype(np.uint8)
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                video_writer.write(frame)
            video_writer.release()

        # Read the video file
        with open(video_path, "rb") as f:
            video_binary = f.read()

        # Store in MinIO
        object_name = f"generated_video_{prompt[:10]}.mp4"
        minio_client.put_object(
            bucket_name,
            object_name,
            io.BytesIO(video_binary),
            len(video_binary),
            content_type="video/mp4"
        )
        logger.info(f"Video stored in MinIO at {object_name}")

        # Generate presigned URL
        presigned_url = minio_client.presigned_get_object(bucket_name, object_name)


        # Clean up temporary file
        os.remove(video_path)

        return {"status": "success", "video_url": presigned_url}

    except Exception as e:
        logger.error(f"Error generating video: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

