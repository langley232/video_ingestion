#!/bin/bash
# Start Ollama in the background
/bin/ollama serve &
# Record Process ID
pid=$!
# Pause for Ollama to start
sleep 5
echo "🔴 Pulling models..."
# Check if OLLAMA_MODELS is set
if [ -z "$OLLAMA_MODELS" ]; then
  echo "No models specified in OLLAMA_MODELS environment variable."
  exit 1
fi
# Split OLLAMA_MODELS by comma and pull each model
IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
for model in "${MODELS[@]}"; do
  ollama pull "$model"
done
echo "🟢 Done!"
# Wait for Ollama process to finish
wait $pid
