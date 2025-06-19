import os
import json
import torch
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import io
from typing import List, Optional
import logging
import numpy as np

logger = logging.getLogger(__name__)


class DroneDataset(Dataset):
    def __init__(self, images, labels):
        self.images = images
        self.labels = labels

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        return self.images[idx], self.labels[idx]


class DatasetManager:
    def __init__(self, minio_client):
        self.minio_client = minio_client
        self.bucket_name = "drone-training-data"

    def _load_image(self, image_data):
        """Load and preprocess image from bytes optimized for GPU"""
        try:
            image = Image.open(io.BytesIO(image_data))
            # Convert to RGB if needed
            if image.mode != 'RGB':
                image = image.convert('RGB')
            # Resize to model's expected size
            image = image.resize((224, 224))
            # Convert to tensor and normalize
            image_tensor = torch.tensor(np.array(image)).float()
            image_tensor = image_tensor.permute(2, 0, 1) / 255.0
            return image_tensor
        except Exception as e:
            logger.error(f"Error loading image: {str(e)}")
            return None

    def _load_metadata(self, metadata_data):
        """Load metadata from bytes"""
        try:
            return json.loads(metadata_data.decode())
        except Exception as e:
            logger.error(f"Error loading metadata: {str(e)}")
            return None

    def _encode_labels(self, labels):
        """Encode string labels to integers"""
        unique_labels = list(set(labels))
        label_to_idx = {label: idx for idx, label in enumerate(unique_labels)}
        return [label_to_idx[label] for label in labels], label_to_idx

    def prepare_dataset(self, categories: Optional[List[str]] = None, batch_size: int = 16):
        """Prepare dataset from MinIO storage optimized for A10 GPU"""
        try:
            images = []
            labels = []

            # List all objects in the images directory
            objects = self.minio_client.list_objects(
                self.bucket_name,
                prefix="images/",
                recursive=True
            )

            logger.info("Loading images from MinIO...")

            for obj in objects:
                # Skip if not in selected categories
                if categories and not any(cat in obj.object_name for cat in categories):
                    continue

                # Get image data
                image_data = self.minio_client.get_object(
                    self.bucket_name,
                    obj.object_name
                ).read()

                # Get corresponding metadata
                metadata_path = f"metadata/{obj.object_name.split('images/')[1]}.json"
                try:
                    metadata = self.minio_client.get_object(
                        self.bucket_name,
                        metadata_path
                    ).read()
                    metadata = self._load_metadata(metadata)
                except:
                    metadata = None

                # Load and preprocess image
                image_tensor = self._load_image(image_data)
                if image_tensor is not None:
                    images.append(image_tensor)
                    # Use category from path or metadata
                    category = obj.object_name.split('/')[1]
                    labels.append(category)

            if not images:
                raise ValueError("No images found matching the criteria")

            # Encode labels
            encoded_labels, label_mapping = self._encode_labels(labels)

            # Convert to tensors
            images_tensor = torch.stack(images)
            labels_tensor = torch.tensor(encoded_labels, dtype=torch.long)

            logger.info(
                f"Dataset prepared: {len(images)} images, {len(set(labels))} categories")
            logger.info(f"Label mapping: {label_mapping}")

            # Create dataset
            dataset = DroneDataset(images_tensor, labels_tensor)

            # Create dataloader with GPU optimizations
            dataloader = DataLoader(
                dataset,
                batch_size=batch_size,
                shuffle=True,
                num_workers=4,  # Increased for better performance
                pin_memory=True,  # Faster data transfer to GPU
                drop_last=True,  # Avoid incomplete batches
                persistent_workers=True  # Keep workers alive between epochs
            )

            return dataloader

        except Exception as e:
            logger.error(f"Error preparing dataset: {str(e)}")
            raise
