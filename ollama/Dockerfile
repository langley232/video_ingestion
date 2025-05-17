FROM ollama/ollama:latest

# Install curl
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose Ollama port
EXPOSE 11434

# Set entrypoint
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
