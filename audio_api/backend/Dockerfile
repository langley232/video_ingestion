# Use official Python slim image for a smaller footprint
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
# Explicitly upgrade pip first
RUN pip install --no-cache-dir --upgrade pip

# Now install requirements, which should benefit from the upgraded pip
# Also, ensure 'elevenlabs' is at the specified version and its dependencies are met
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY main.py .

# Expose port 8000 for FastAPI
EXPOSE 8000

# Command to run the FastAPI app with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
