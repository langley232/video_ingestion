import torch
import torch.nn as nn
from transformers import AutoModelForVision2Seq, AutoProcessor
import logging

logger = logging.getLogger(__name__)


class MoondreamModel(nn.Module):
    def __init__(self):
        super().__init__()
        # Load base model and processor
        self.model = AutoModelForVision2Seq.from_pretrained(
            "vikhyatk/moondream2", trust_remote_code=True)
        self.processor = AutoProcessor.from_pretrained(
            "vikhyatk/moondream2", trust_remote_code=True)

        # Freeze base model parameters
        for param in self.model.parameters():
            param.requires_grad = False

        # Add classification head
        self.classifier = nn.Sequential(
            nn.Linear(self.model.config.hidden_size, 512),
            nn.ReLU(),
            nn.Dropout(0.1),
            # 3 categories: military, commercial, recreational
            nn.Linear(512, 3)
        )

    def forward(self, images, labels=None):
        # Process images through base model
        outputs = self.model(images)

        # Get pooled output
        pooled_output = outputs.last_hidden_state.mean(dim=1)

        # Pass through classifier
        logits = self.classifier(pooled_output)

        if labels is not None:
            loss_fn = nn.CrossEntropyLoss()
            loss = loss_fn(logits, labels)
            return loss, logits

        return logits

    def save(self, path):
        """Save model state"""
        torch.save({
            'model_state_dict': self.state_dict(),
            'processor': self.processor
        }, path)

    def load(self, path):
        """Load model state"""
        checkpoint = torch.load(path)
        self.load_state_dict(checkpoint['model_state_dict'])
        self.processor = checkpoint['processor']
