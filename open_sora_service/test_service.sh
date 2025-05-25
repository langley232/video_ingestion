#!/bin/bash

# Script to test the Open-Sora video generation service

SERVICE_HOST="localhost"
SERVICE_PORT="8000" # Assuming the Docker container maps port 8000 to localhost:8000

ENDPOINT_URL="http://${SERVICE_HOST}:${SERVICE_PORT}/generate-video/"

# --- Test Case 1: Basic 256px video ---
echo "Sending request for a 256px video..."
curl -X POST "${ENDPOINT_URL}" \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "a cat wearing a superhero costume, flying through a cityscape",
           "num_frames": 17,
           "resolution": "256px",
           "aspect_ratio": "1:1"
         }' \
     -o response_256px.json

echo ""
echo "Response saved to response_256px.json"
echo "Check the JSON file for the video URL."
echo ""

# --- Test Case 2: 768px video (optional, can be demanding) ---
# echo "Sending request for a 768px video (this might take a while and require significant resources)..."
# curl -X POST "${ENDPOINT_URL}" \
#      -H "Content-Type: application/json" \
#      -d '{
#            "prompt": "a majestic dragon soaring through a cloudy sky, epic fantasy",
#            "num_frames": 17,
#            "resolution": "768px",
#            "aspect_ratio": "16:9"
#          }' \
#      -o response_768px.json
#
# echo ""
# echo "Response saved to response_768px.json"
# echo "Check the JSON file for the video URL."
# echo ""

# --- Test Case 3: Health Check ---
echo "Checking service health..."
curl "http://${SERVICE_HOST}:${SERVICE_PORT}/health"
echo ""
echo ""

echo "Testing complete. Make sure the Docker container for open_sora_service is running and port 8000 is mapped."
