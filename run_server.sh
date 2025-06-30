#!/bin/bash

# Get the host's IP address (adjust the interface name if needed)
HOST_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)192\.168\.\d+\.\d+' | head -1)

if [ -z "$HOST_IP" ]; then
    echo "Could not determine host IP address"
    exit 1
fi

echo "Starting WebRTC server with host IP: $HOST_IP"

# Run with host network mode and GPU support
docker run --rm \
    --gpus all \
    --network host \
    -e HOST_IP=$HOST_IP \
    chobinbeats