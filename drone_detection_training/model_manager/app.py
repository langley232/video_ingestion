from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
from minio import Minio
from minio.error import S3Error
import json
import logging
import subprocess
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

# Constants
BUCKET_NAME = "drone-training-data"
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")


class ModelDeployment(BaseModel):
    model_name: str
    version: Optional[str] = None


@app.get("/models")
async def list_models():
    """List all available models"""
    try:
        models = []
        objects = minio_client.list_objects(
            BUCKET_NAME,
            prefix="models/",
            recursive=True
        )

        for obj in objects:
            if obj.object_name.endswith(".pt"):
                models.append({
                    "name": obj.object_name.split("/")[-1],
                    "size": obj.size,
                    "last_modified": obj.last_modified
                })

        return {
            "status": "success",
            "models": models
        }

    except Exception as e:
        logger.error(f"Error listing models: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/deploy")
async def deploy_model(deployment: ModelDeployment):
    """Deploy model to Ollama"""
    try:
        # Get model from MinIO
        model_path = f"models/{deployment.model_name}"
        if not deployment.version:
            # Get latest version
            objects = minio_client.list_objects(
                BUCKET_NAME,
                prefix=model_path,
                recursive=True
            )
            versions = [obj.object_name for obj in objects]
            if not versions:
                raise HTTPException(status_code=404, detail="Model not found")
            model_path = max(versions)

        # Download model
        model_data = minio_client.get_object(
            BUCKET_NAME,
            model_path
        ).read()

        # Save model locally
        local_path = f"/tmp/{os.path.basename(model_path)}"
        with open(local_path, "wb") as f:
            f.write(model_data)

        # Create Ollama model
        model_name = "moondream-finetuned"
        create_cmd = [
            "ollama", "create",
            model_name,
            "-f", local_path
        ]

        result = subprocess.run(
            create_cmd,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Error creating Ollama model: {result.stderr}"
            )

        return {
            "status": "success",
            "model_name": model_name,
            "message": "Model deployed successfully"
        }

    except Exception as e:
        logger.error(f"Error deploying model: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
