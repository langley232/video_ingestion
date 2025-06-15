#!/bin/bash

# Start Ollama in the background
/bin/ollama serve &
pid=$!

# Give Ollama a moment to start
sleep 5

# Pull models if specified
if [ ! -z "$OLLAMA_MODELS" ]; then
    echo "Pulling models: $OLLAMA_MODELS"
    IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
    for model in "${MODELS[@]}"; do
        ollama pull "$model"
    done
fi

# Wait for Ollama process
wait $pid
