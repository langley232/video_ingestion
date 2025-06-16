from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
from minio import Minio
from minio.error import S3Error
import json
import logging
from training.trainer import ModelTrainer
from training.dataset import DatasetManager

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

# Initialize dataset manager and trainer
dataset_manager = DatasetManager(minio_client)
trainer = ModelTrainer()


class TrainingConfig(BaseModel):
    epochs: int = 3
    batch_size: int = 8
    learning_rate: float = 1e-5
    categories: Optional[List[str]] = None


@app.post("/prepare-dataset")
async def prepare_dataset(config: TrainingConfig):
    try:
        # Prepare dataset from MinIO
        dataset = dataset_manager.prepare_dataset(
            categories=config.categories,
            batch_size=config.batch_size
        )

        return {
            "status": "success",
            "dataset_size": len(dataset),
            "categories": config.categories or "all"
        }
    except Exception as e:
        logger.error(f"Error preparing dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/train")
async def train_model(config: TrainingConfig):
    try:
        # Prepare dataset
        dataset = dataset_manager.prepare_dataset(
            categories=config.categories,
            batch_size=config.batch_size
        )

        # Train model
        training_results = trainer.train(
            dataset=dataset,
            epochs=config.epochs,
            learning_rate=config.learning_rate
        )

        # Save model
        model_path = trainer.save_model()

        # Upload model to MinIO
        with open(model_path, 'rb') as f:
            minio_client.put_object(
                "drone-training-data",
                f"models/moondream_finetuned_{training_results['timestamp']}.pt",
                f,
                os.path.getsize(model_path)
            )

        return {
            "status": "success",
            "training_results": training_results,
            "model_path": model_path
        }

    except Exception as e:
        logger.error(f"Error training model: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
