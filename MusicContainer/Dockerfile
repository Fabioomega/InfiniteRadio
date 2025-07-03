# =============================================================================
# BASE IMAGE AND ENVIRONMENT SETUP
# =============================================================================
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

# Avoid prompts during package installs
ENV DEBIAN_FRONTEND=noninteractive

# Create working directory
WORKDIR /app

# =============================================================================
# SYSTEM PACKAGES
# =============================================================================
# Install all system packages in one layer to minimize image size
RUN apt update && apt install -y \
  # Python and build tools
  python3.10 python3.10-venv python3.10-dev python3.10-distutils \
  build-essential cmake git curl wget \
  # Python library dependencies
  libffi-dev libssl-dev libsndfile1 ffmpeg \
  # Audio packages
  libportaudio2 \
  # Opus development libraries
  libopus-dev libopusfile-dev pkg-config \
  # Process management
  supervisor \
  && rm -rf /var/lib/apt/lists/*

# =============================================================================
# PYTHON SETUP
# =============================================================================
# Set up Python 3.10 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

# Install pip for Python 3.10
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python

# =============================================================================
# PYTHON DEPENDENCIES
# =============================================================================
# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# =============================================================================
# MAGENTA REALTIME SETUP
# =============================================================================
# Clone Magenta Realtime and install with GPU extras
RUN git clone https://github.com/magenta/magenta-realtime.git && \
    sed -i "s/DEFAULT_SOURCE = 'gcp'/DEFAULT_SOURCE = 'hf'/" magenta-realtime/magenta_rt/asset.py && \
    pip install -e magenta-realtime/[gpu]

# Clean out conflicting TensorFlow packages and reinstall specific nightlies
RUN pip uninstall -y tensorflow tf-nightly tensorflow-cpu tf-nightly-cpu \
    tensorflow-tpu tf-nightly-tpu tensorflow-hub tf-hub-nightly \
    tensorflow-text tensorflow-text-nightly && \
    pip install \
      tf-nightly==2.20.0.dev20250619 \
      tensorflow-text-nightly==2.20.0.dev20250316 \
      tf-hub-nightly

# =============================================================================
# MODEL SETUP
# =============================================================================
# Copy and run model setup script to pre-download models
COPY setup_model.py .
RUN python setup_model.py

# =============================================================================
# GO SETUP
# =============================================================================
# Install Go for WebRTC server
RUN curl -LO https://go.dev/dl/go1.21.10.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.21.10.linux-amd64.tar.gz && \
    ln -s /usr/local/go/bin/go /usr/bin/go && \
    rm go1.21.10.linux-amd64.tar.gz

# Copy Go files and build WebRTC server
COPY go.mod webrtc_server.go ./
RUN go mod download && go mod tidy && \
    go build -o webrtc_server webrtc_server.go

# =============================================================================
# APPLICATION FILES
# =============================================================================
# Copy Python scripts and init script
COPY music_server.py music_server_pipe.py init_pipe.sh ./
RUN chmod +x init_pipe.sh

# Copy supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# =============================================================================
# FINAL CONFIGURATION
# =============================================================================
# Expose port for web server
EXPOSE 8080

# Run both processes with supervisor
ENTRYPOINT ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

