FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip python3-dev git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set up Python environment
RUN pip3 install --upgrade pip

# Install PyTorch with CUDA 12.4
RUN pip3 install torch==2.4.1 torchvision --index-url https://download.pytorch.org/whl/cu124

# Install Diffusers and dependencies with specific transformers version
RUN pip3 install diffusers accelerate imageio-ffmpeg torchao fastapi uvicorn
RUN pip3 install git+https://github.com/huggingface/transformers.git@e6f7149  # Pin to a commit with CogVideoX support (e.g., e6f7149 from 2024-10)

# Set working directory
WORKDIR /app

# Download CogVideoX-5B-I2V model
RUN pip3 install "huggingface_hub[cli]" && \
    huggingface-cli download THUDM/CogVideoX-5B-I2V --local-dir ./model --include "*.safetensors" "*.json"

# Copy inference script
COPY inference.py /app/inference.py

# Set entrypoint
CMD ["uvicorn", "inference.py:app", "--host", "0.0.0.0", "--port", "8002"]
