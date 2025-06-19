import torch
import torch.nn as nn
from unsloth import FastLanguageModel
from transformers import AutoProcessor

import logging

logger = logging.getLogger(__name__)


class Qwen2VLModel(nn.Module):
    def __init__(self):
        super().__init__()
        # Load Qwen2.5VL-3B with Unsloth
        self.model, self.tokenizer = FastLanguageModel.from_pretrained(
            model_name="Qwen/Qwen2.5-VL-3B",
            max_seq_length=2048,
            dtype=None,
            load_in_4bit=True,  # or False if you want full precision
        )
        self.processor = AutoProcessor.from_pretrained(
            "Qwen/Qwen2.5-VL-3B", trust_remote_code=True
        )

        # Freeze base model parameters
        for param in self.model.parameters():
            param.requires_grad = False

        # Add classification head (adjust hidden_size as needed for Qwen2.5VL)
        self.classifier = nn.Sequential(
            nn.Linear(self.model.config.hidden_size, 512),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(512, 3)  # 3 categories
        )

    def forward(self, images, labels=None):
        # Prepare inputs for Qwen2.5VL-3B
        inputs = self.processor(images=images, return_tensors="pt")
        for k, v in inputs.items():
            if v is not None:
                inputs[k] = v.to(self.model.device)

        outputs = self.model(**inputs)
        pooled_output = outputs.last_hidden_state.mean(dim=1)
        logits = self.classifier(pooled_output)

        if labels is not None:
            loss_fn = nn.CrossEntropyLoss()
            loss = loss_fn(logits, labels)
            return loss, logits

        return logits

    def save(self, path):
        """Save model state (of the custom Qwen2VLModel wrapper)"""
        torch.save({
            'model_state_dict': self.state_dict(),
        }, path)

    def load(self, path):
        """Load model state (of the custom Qwen2VLModel wrapper)"""
        checkpoint = torch.load(path)
        self.load_state_dict(checkpoint['model_state_dict'])
