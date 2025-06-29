FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

# Avoid prompts during package installs
ENV DEBIAN_FRONTEND=noninteractive

# System packages
RUN apt update && apt install -y \
  python3.10 python3.10-venv python3.10-dev python3.10-distutils \
  build-essential cmake git curl wget \
  libffi-dev libssl-dev libsndfile1 ffmpeg \
  && rm -rf /var/lib/apt/lists/*

# Set up Python 3.10 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

# Install pip for Python 3.10
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python

# Create working dir
WORKDIR /app

# Copy and install Python deps
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Clone Magenta Realtime and install with GPU extras
RUN git clone https://github.com/magenta/magenta-realtime.git && \
    sed -i "s/DEFAULT_SOURCE = 'gcp'/DEFAULT_SOURCE = 'hf'/" magenta-realtime/magenta_rt/asset.py && \
    pip install -e magenta-realtime/[gpu]

# Clean out conflicting TFs and reinstall specific nightlies
RUN pip uninstall -y tensorflow tf-nightly tensorflow-cpu tf-nightly-cpu \
    tensorflow-tpu tf-nightly-tpu tensorflow-hub tf-hub-nightly \
    tensorflow-text tensorflow-text-nightly && \
    pip install \
      tf-nightly==2.20.0.dev20250619 \
      tensorflow-text-nightly==2.20.0.dev20250316 \
      tf-hub-nightly

# Copy and run model setup script to pre-download models
COPY setup_model.py .
RUN python setup_model.py

# TODO: put these eariler once I know they work
# Install audio packages for sounddevice
RUN apt update && apt install -y \
    libportaudio2

# Copy the test script
COPY test.py .

# Run the Python script directly
ENTRYPOINT ["python", "test.py"]


