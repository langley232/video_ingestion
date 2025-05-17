FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies including OpenGL for OpenCV
RUN apt-get update && apt-get install -y \
    python3-pip \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set up Python environment
RUN pip3 install --upgrade pip

# Install Python dependencies with verification
COPY requirements.txt /app/requirements.txt
RUN pip3 install -r /app/requirements.txt && \
    python3 -c "import cv2; print('OpenCV version:', cv2.__version__)" || exit 1

# Set working directory and permissions
WORKDIR /app
RUN chown -R 1000:1000 /app

# Copy streamlit script
COPY app.py /app/app.py

# Add non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Set entrypoint
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
