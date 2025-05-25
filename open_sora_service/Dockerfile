# Builder Stage: Clone Open-Sora, install dependencies, and download model
FROM nvidia/cuda:12.2.0-devel-ubuntu22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive

# Install Python 3.10, pip, and git
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    git \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set python3.10 as default python and pip
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Clone Open-Sora repository
WORKDIR /app
RUN git clone https://github.com/hpcaitech/Open-Sora.git open-sora
WORKDIR /app/open-sora
RUN git checkout main

# Install Open-Sora dependencies
# First install general dependencies, then specific ones like xformers and flash-attn
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir xformers==0.0.27.post2 --index-url https://download.pytorch.org/whl/cu121
RUN pip install --no-cache-dir flash-attn --no-build-isolation

# Ensure torch >= 2.4.0 (Open-Sora requirements should handle this, but can be explicit if needed)
# RUN pip install --no-cache-dir "torch>=2.4.0"

# Install huggingface_hub for downloading models
RUN pip install --no-cache-dir huggingface_hub[cli]

# Download Open-Sora model
RUN huggingface-cli download hpcai-tech/Open-Sora-v2 --local-dir /app/open-sora-model-cache/Open-Sora-v2 --local-dir-use-symlinks False

# Runtime Stage: Minimal Image with application and model
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive

# Install runtime OS dependencies (Python, ffmpeg, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set python3.10 as default python and pip
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

WORKDIR /app

# Copy Python environment from builder
# This includes Open-Sora and its dependencies
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy downloaded model
COPY --from=builder /app/open-sora-model-cache/Open-Sora-v2 /app/open-sora-model-cache/Open-Sora-v2

# Copy application code and its requirements (placeholders for now)
COPY ./main.py /app/main.py
COPY ./requirements.txt /app/requirements.txt

# Install FastAPI application requirements
# This requirements.txt will contain FastAPI, uvicorn, etc.
RUN if [ -f /app/requirements.txt ]; then pip install --no-cache-dir -r /app/requirements.txt; fi

# Expose the API port
EXPOSE 8000

# Command to run the FastAPI application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
