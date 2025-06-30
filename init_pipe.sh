#!/bin/bash
# Create the named pipe if it doesn't exist
PIPE_PATH="/tmp/audio_pipe"
if [ ! -p "$PIPE_PATH" ]; then
    mkfifo "$PIPE_PATH"
    echo "Named pipe created at $PIPE_PATH"
else
    echo "Named pipe already exists at $PIPE_PATH"
fi