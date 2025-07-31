# Infinite Radio

Infinite Radio generates endless music that automatically changes based on your current context. It combines the [Magenta RealTime](https://magenta.withgoogle.com/magenta-realtime) music model with contextual genre selection either from [InternVL3](https://huggingface.co/OpenGVLab/InternVL3-2B) or the top processes running on your machine.

# Installation

## Prerequisites

For running the music model locally, you will need:
- **Docker** with GPU support
- **NVIDIA GPU** with CUDA support
- **[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)**

## Music Model

1. **Run the Docker Container from [Dockerhub](https://hub.docker.com/repository/docker/lauriewired/musicbeats/general):**
   ```bash
   docker run --gpus all --network host lauriewired/musicbeats:latest
   ```

2. **Access the web interface:**
   - Open your browser and navigate to `http://localhost:8080`
   - Click the play button to start streaming
  
## Running a DJ

## Option 1: Running the DJ on MacOS

TODO

## Option 2: Running Process DJ with Python

The Process DJ will monitor the processes on your system and automatically change music genres based on what applications are most active.

```bash
python process_dj.py localhost 8080 # Point this to the IP and port of the music model
```

## Option 3: Running the LLM DJ with Python

# API Reference

## Change Genre

**POST** `/genre`

```bash
curl -X POST http://localhost:8080/genre \
  -H "Content-Type: application/json" \
  -d '{"genre": "jazz"}'
```

## Get Current Genre

**GET** `/current-genre`

```bash
curl http://localhost:8080/current-genre
```

# Building

Building the Mac application:

```
pip install py2app jaraco.text setuptools
python3 setup.py py2app
```
