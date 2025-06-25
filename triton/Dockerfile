FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy model setup script
COPY setup_triton.py .

# Create models directory
RUN mkdir -p /app/triton_models

# Set environment variables
ENV TRITON_MODELS_DIR=/app/triton_models

# Run model setup
CMD ["python", "setup_triton.py"] 