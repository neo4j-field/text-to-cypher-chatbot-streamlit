#!/bin/bash

# Define your Docker image and container name
IMAGE_NAME="cummins-streamlit-app-test"
CONTAINER_NAME="cummins_streamlit_container"


docker stop $(docker ps -aq)
docker rm $(docker ps -aq)
docker rmi $(docker images -q)


# Step 1: Build the Docker Image
echo "Building Docker image..."
docker build -t $IMAGE_NAME .

# Check if the container is already running
RUNNING_CONTAINER=$(docker ps --filter "name=$CONTAINER_NAME" -q)

if [ ! -z "$RUNNING_CONTAINER" ]; then
    echo "Found a running container with the name $CONTAINER_NAME. Stopping it..."
    docker stop $RUNNING_CONTAINER
fi

# Step 2: Run the Docker Container
# Note: Adjust the port mappings if necessary
echo "Running Docker container..."
docker run --env-file /Users/alexanderfournier/PycharmProjects/streamlit-text-to-cypher/.env -p 8501:8501 --name $CONTAINER_NAME $IMAGE_NAME
