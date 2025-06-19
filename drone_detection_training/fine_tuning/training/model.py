import torch
import torch.nn as nn
from transformers import AutoProcessor, AutoModelForCausalLM # Correct import

import logging

logger = logging.getLogger(__name__)


class MoondreamModel(nn.Module):
    def __init__(self):
        super().__init__()
        # Load base model and processor using AutoModelForCausalLM
        self.model = AutoModelForCausalLM.from_pretrained(
            "vikhyatk/moondream2", 
            trust_remote_code=True,
            # Add device_map if you have multiple GPUs, e.g., device_map="auto"
        )
        self.processor = AutoProcessor.from_pretrained(
            "vikhyatk/moondream2", trust_remote_code=True
        )

        # Freeze base model parameters
        for param in self.model.parameters():
            param.requires_grad = False

        # Add classification head
        # IMPORTANT: Verify 'self.model.config.hidden_size' or find the correct output dimension
        # The hidden_size here typically refers to the dimension of the language model's embeddings.
        # You need to ensure this matches the feature dimension you're extracting for classification.
        # If outputs.last_hidden_state is (batch_size, sequence_length, hidden_size), then mean(dim=1)
        # will yield (batch_size, hidden_size). This should be correct.
        self.classifier = nn.Sequential(
            nn.Linear(self.model.config.hidden_size, 512), 
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(512, 3) # 3 categories
        )

    def forward(self, images, labels=None):
        # Ensure images are processed correctly for the Moondream model
        # The 'images' input to this forward method should be PIL Images or similar,
        # which the processor can handle.
        
        # Prepare inputs: This will generate pixel_values, input_ids, attention_mask
        # Default text input might be empty or a specific prompt depending on fine-tuning strategy
        # For pure image classification, you might need a dummy text input or
        # adjust how Moondream processes.
        # Typically, for Moondream, you'd feed the image and a text prompt.
        # For *just* classification, consider if you need a generic prompt or if you're
        # only relying on the vision features.
        
        # This is a critical point: Moondream is a VLM. For classification,
        # you might need to extract features from its *vision encoder* directly
        # or rely on its combined output when a simple "classify" prompt is given.
        # Let's assume for now your 'images' input is just the image data.
        
        # If your 'images' are PIL Images, the processor will handle them.
        inputs = self.processor(images=images, return_tensors="pt") 
        
        # Move inputs to the correct device
        # Assuming 'self.device' is set by your trainer.py (e.g., to 'cuda' or 'cpu')
        # If not, you'll need to define 'self.device' in __init__
        # Example: self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        for k, v in inputs.items():
            if v is not None: # Check if tensor is not None before moving
                inputs[k] = v.to(self.model.device) # Use self.model.device or a predefined self.device

        # Pass through base Moondream model
        # This will return a CausalLMOutputWithPast or similar, containing hidden states.
        outputs = self.model(**inputs)

        # Extract pooled output for classification
        # For a causal language model, `last_hidden_state` is the output of the LM.
        # Taking the mean(dim=1) might be a simplistic way to pool for classification.
        # If your fine-tuning strategy relies on a specific token's hidden state (e.g., CLS token equivalent)
        # or features directly from the vision encoder, this line might need adjustment.
        pooled_output = outputs.last_hidden_state.mean(dim=1)

        # Pass through classifier
        logits = self.classifier(pooled_output)

        if labels is not None:
            loss_fn = nn.CrossEntropyLoss()
            loss = loss_fn(logits, labels)
            return loss, logits

        return logits

    def save(self, path):
        """Save model state (of the custom MoondreamModel wrapper)"""
        torch.save({
            'model_state_dict': self.state_dict(),
            # It's generally not recommended to save the processor object directly in the model state_dict
            # as it can cause issues with different Python/library versions.
            # If you need to save the processor config, save it separately or rely on from_pretrained.
        }, path)
        # Optionally, save the base model and processor using Hugging Face's methods
        # self.model.save_pretrained(path + "_base_model")
        # self.processor.save_pretrained(path + "_processor")


    def load(self, path):
        """Load model state (of the custom MoondreamModel wrapper)"""
        checkpoint = torch.load(path)
        self.load_state_dict(checkpoint['model_state_dict'])
        # If you saved the base model and processor separately, load them here:
        # self.model = AutoModelForCausalLM.from_pretrained(path + "_base_model", trust_remote_code=True)
        # self.processor = AutoProcessor.from_pretrained(path + "_processor", trust_remote_code=True)
