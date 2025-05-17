# Build Stage: Download Model
FROM nvidia/cuda:12.2.0-devel-ubuntu22.04 AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --upgrade pip diffusers torch accelerate transformers
COPY download_model.py /app/download_model.py
RUN chmod +x /app/download_model.py && python3 /app/download_model.py

# Runtime Stage: Minimal Image
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04 AS runtime

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ffmpeg \
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    && rm -rf /var/lib/apt/lists/*

# Set up Python virtual environment
RUN python3.10 -m venv /venv
ENV PATH="/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip

# Copy Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Upgrade diffusers
RUN pip install --no-cache-dir --upgrade diffusers

# Set work directory
WORKDIR /app

# Copy application code and pre-downloaded model
COPY . /app
COPY --from=builder /app/cache/models/wan2.1-t2v-1.3b /app/cache/models/wan2.1-t2v-1.3b

# Expose the API port
EXPOSE 8002

# Command to run the API
CMD ["uvicorn", "inference:app", "--host", "0.0.0.0", "--port", "8002"]
