from diffusers import DiffusionPipeline
import torch
import os

# Set cache directory
os.environ["HF_HOME"] = "/app/cache/huggingface"

# Download Wan 2.1 T2V-1.3B model
pipe = DiffusionPipeline.from_pretrained(
    "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
    torch_dtype=torch.float16,
    use_safetensors=True,
    low_cpu_mem_usage=True
)
pipe.save_pretrained("/app/cache/models/wan2.1-t2v-1.3b")
