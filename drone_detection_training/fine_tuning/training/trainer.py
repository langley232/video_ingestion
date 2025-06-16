import torch
import torch.nn as nn
from torch.optim import AdamW
from datetime import datetime
import os
import logging
from .model import MoondreamModel

logger = logging.getLogger(__name__)


class ModelTrainer:
    def __init__(self):
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu")
        self.model = MoondreamModel().to(self.device)

    def train(self, dataset, epochs=3, learning_rate=1e-5):
        """Train the model"""
        try:
            # Initialize optimizer
            optimizer = AdamW(self.model.parameters(), lr=learning_rate)

            # Training loop
            self.model.train()
            total_loss = 0
            total_steps = 0

            for epoch in range(epochs):
                epoch_loss = 0
                epoch_steps = 0

                for batch in dataset:
                    images, labels = batch
                    images = images.to(self.device)
                    labels = labels.to(self.device)

                    # Forward pass
                    loss, _ = self.model(images, labels)

                    # Backward pass
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()

                    epoch_loss += loss.item()
                    epoch_steps += 1

                avg_epoch_loss = epoch_loss / epoch_steps
                total_loss += epoch_loss
                total_steps += epoch_steps

                logger.info(
                    f"Epoch {epoch+1}/{epochs}, Loss: {avg_epoch_loss:.4f}")

            # Calculate average loss
            avg_loss = total_loss / total_steps

            # Prepare results
            results = {
                "timestamp": datetime.utcnow().isoformat(),
                "epochs": epochs,
                "learning_rate": learning_rate,
                "final_loss": avg_loss,
                "device": str(self.device)
            }

            return results

        except Exception as e:
            logger.error(f"Error during training: {str(e)}")
            raise

    def save_model(self):
        """Save the trained model"""
        try:
            # Create models directory if it doesn't exist
            os.makedirs("models", exist_ok=True)

            # Generate model path
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            model_path = f"models/moondream_finetuned_{timestamp}.pt"

            # Save model
            self.model.save(model_path)
            logger.info(f"Model saved to {model_path}")

            return model_path

        except Exception as e:
            logger.error(f"Error saving model: {str(e)}")
            raise
