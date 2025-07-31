#!/bin/bash

# Change to the MusicContainer directory
cd "$(dirname "$0")/MusicContainer"

echo "Starting WebRTC server on localhost"

# Run with host network mode and GPU support
docker run --rm \
    --gpus all \
    --network host \
    musicbeats