FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

# Install Python, OpenGL, and dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install requirements
RUN pip3 install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt && \
    python3 -c "import cv2; print('OpenCV version:', cv2.__version__)" || exit 1

# Set working directory
WORKDIR /app

# Copy application code
COPY app.py /app/app.py

# Run storage script (overridden by docker-compose.yml)
CMD ["python3", "/app/app.py"]
