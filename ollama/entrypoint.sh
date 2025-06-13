#!/bin/bash

# Start Ollama server in the background
echo "Starting Ollama server..."
ollama serve &

# Capture the PID
pid=$!

# Wait for Ollama server to be ready
echo "Waiting for Ollama server to start..."
for i in {1..30}; do
    if curl -f http://0.0.0.0:11434 > /dev/null 2>&1; then
        echo "Ollama server is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Ollama server failed to start"
        exit 1
    fi
    sleep 5
done

# Pull models specified in OLLAMA_MODELS environment variable
echo "Checking for models: $OLLAMA_MODELS"
IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
for MODEL in "${MODELS[@]}"; do
    if ollama list | grep -q "$MODEL"; then
        echo "Model $MODEL already available."
    else
        echo "Pulling model: $MODEL"
        ollama pull "$MODEL"
        if [ $? -eq 0 ]; then
            echo "Model $MODEL pulled successfully!"
        else
            echo "Failed to pull model $MODEL"
            exit 1
        fi
    fi
done

# Verify models are listed
echo "Verifying models in /api/tags"
for MODEL in "${MODELS[@]}"; do
    if curl -f http://0.0.0.0:11434/api/tags | grep -q "$MODEL"; then
        echo "Model $MODEL found in /api/tags"
    else
        echo "Model $MODEL not found in /api/tags"
        exit 1
    fi
done

# Wait for the Ollama process to finish
wait $pid
