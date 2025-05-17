#!/bin/bash

# Start Kafka server using the image's entrypoint
echo "Starting Kafka broker..."
/usr/bin/kafka-server-start /etc/kafka/server.properties &

# Capture the PID
pid=$!

# Wait for Kafka broker to be ready
echo "Waiting for Kafka broker to be ready..."
until nc -z localhost 9092; do
    echo "Kafka broker not ready, retrying in 5 seconds..."
    sleep 5
done
echo "Kafka broker is ready."

# Keep the container running
wait $pid
