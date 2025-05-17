#!/bin/bash

# Variables
KAFKA_CONTAINER="video_ingestion-kafka-1"
TOPIC_NAME="video-ingestion"
BOOTSTRAP_SERVER="kafka:9092"
REPLICATION_FACTOR=1
PARTITIONS=1
CONFIG="retention.ms=-1"

# Check if the Kafka container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${KAFKA_CONTAINER}$"; then
    echo "Error: Kafka container '${KAFKA_CONTAINER}' is not running. Please start it with 'sudo docker compose up -d'."
    exit 1
fi

# Execute the kafka-topics command inside the container
echo "Creating topic '${TOPIC_NAME}'..."
sudo docker exec ${KAFKA_CONTAINER} /usr/bin/kafka-topics \
    --create \
    --topic ${TOPIC_NAME} \
    --bootstrap-server ${BOOTSTRAP_SERVER} \
    --replication-factor ${REPLICATION_FACTOR} \
    --partitions ${PARTITIONS} \
    --config ${CONFIG}

# Check if the topic was created successfully
if [ $? -eq 0 ]; then
    echo "Topic '${TOPIC_NAME}' created successfully."
    # Verify the topic
    echo "Verifying topic creation..."
    sudo docker exec ${KAFKA_CONTAINER} /usr/bin/kafka-topics --list --bootstrap-server ${BOOTSTRAP_SERVER} | grep ${TOPIC_NAME}
else
    echo "Error: Failed to create topic '${TOPIC_NAME}'. Check Kafka logs for details."
    sudo docker logs ${KAFKA_CONTAINER}
    exit 1
fi
