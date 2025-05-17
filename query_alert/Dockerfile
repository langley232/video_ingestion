FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Set up Python environment
RUN pip3 install --upgrade pip

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip3 install -r /app/requirements.txt

# Set working directory and permissions
WORKDIR /app
RUN chown -R 1000:1000 /app

# Copy query_alert script
COPY query_alert.py /app/query_alert.py

# Add non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Set entrypoint
CMD ["python3", "query_alert.py"]
