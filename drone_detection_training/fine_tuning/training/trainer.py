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

        # Optimize for A10 GPU (24GB VRAM)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            # Set memory fraction to avoid OOM
            torch.cuda.set_per_process_memory_fraction(0.9)

    def train(self, dataset, epochs=3, learning_rate=1e-5, batch_size=16):
        """Train the model optimized for A10 GPU"""
        try:
            # Initialize optimizer with weight decay
            optimizer = AdamW(
                self.model.parameters(),
                lr=learning_rate,
                weight_decay=0.01,
                betas=(0.9, 0.999)
            )

            # Learning rate scheduler
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                optimizer,
                T_max=epochs
            )

            # Training loop
            self.model.train()
            total_loss = 0
            total_steps = 0

            for epoch in range(epochs):
                epoch_loss = 0
                epoch_steps = 0

                for batch_idx, batch in enumerate(dataset):
                    try:
                        images, labels = batch
                        images = images.to(self.device, non_blocking=True)
                        labels = labels.to(self.device, non_blocking=True)

                        # Forward pass
                        loss, _ = self.model(images, labels)

                        # Backward pass
                        optimizer.zero_grad()
                        loss.backward()

                        # Gradient clipping
                        torch.nn.utils.clip_grad_norm_(
                            self.model.parameters(), max_norm=1.0)

                        optimizer.step()

                        epoch_loss += loss.item()
                        epoch_steps += 1

                        # Clear cache periodically
                        if batch_idx % 10 == 0:
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()

                        # Log progress
                        if batch_idx % 50 == 0:
                            logger.info(
                                f"Epoch {epoch+1}, Batch {batch_idx}, Loss: {loss.item():.4f}")

                    except RuntimeError as e:
                        if "out of memory" in str(e):
                            logger.error(
                                f"GPU OOM at batch {batch_idx}. Skipping batch.")
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                            continue
                        else:
                            raise e

                # Update learning rate
                scheduler.step()

                avg_epoch_loss = epoch_loss / epoch_steps
                total_loss += epoch_loss
                total_steps += epoch_steps

                logger.info(
                    f"Epoch {epoch+1}/{epochs}, Loss: {avg_epoch_loss:.4f}, LR: {scheduler.get_last_lr()[0]:.6f}")

            # Calculate average loss
            avg_loss = total_loss / total_steps

            # Prepare results
            results = {
                "timestamp": datetime.utcnow().isoformat(),
                "epochs": epochs,
                "learning_rate": learning_rate,
                "batch_size": batch_size,
                "final_loss": avg_loss,
                "device": str(self.device),
                "gpu_memory_used": f"{torch.cuda.memory_allocated()/1024**3:.2f}GB" if torch.cuda.is_available() else "N/A"
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
