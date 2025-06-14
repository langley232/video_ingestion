#!/bin/bash

# Start Ollama server in the background
echo "Starting Ollama server..."
ollama serve &
pid=$!

# Wait for Ollama server to be ready
echo "Waiting for Ollama server to start..."
for i in {1..30}; do
    if curl -f http://localhost:11434 > /dev/null 2>&1; then
        echo "✅ Ollama server is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Ollama server failed to start on time"
        exit 1
    fi
    sleep 5
done

# Test internet connectivity
echo "Testing internet connectivity..."
if curl -fsS --connect-timeout 5 https://google.com > /dev/null; then
    echo "✅ Internet connectivity test passed."
else
    echo "❌ Internet connectivity test failed. This is likely the problem."
    exit 1
fi

# Pull models specified in OLLAMA_MODELS environment variable
echo "Checking for models: $OLLAMA_MODELS"
IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
for MODEL in "${MODELS[@]}"; do
    echo "Processing model: $MODEL"
    # Remove any whitespace from model name
    MODEL=$(echo $MODEL | xargs)
    
    # Check if model exists
    if ollama list | grep -q "$MODEL"; then
        echo "Model $MODEL already available."
    else
        echo "Pulling model: $MODEL"
        # Try pulling the model with retries
        for attempt in {1..3}; do
            echo "Attempt $attempt to pull $MODEL"
            if ollama pull "$MODEL"; then
                echo "✅ Model $MODEL pulled successfully!"
                break
            else
                if [ $attempt -eq 3 ]; then
                    echo "❌ Failed to pull model $MODEL after 3 attempts"
                    exit 1
                fi
                echo "Retrying in 10 seconds..."
                sleep 10
            fi
        done
    fi
done

echo "✅ All models are available."
echo "Container will now wait for the Ollama server process to exit."
# Wait for the Ollama process to finish
wait $pid
