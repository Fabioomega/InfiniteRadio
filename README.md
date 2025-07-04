# Infinite Radio

Infinite Radio is a music streaming system that generates endless, unique music in real-time using Google's Magenta Realtime AI models. It features automatic genre switching based on your running applications.

## Quick Start

### Prerequisites

- **Docker** with GPU support
- **NVIDIA GPU** with CUDA support
- **[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)**
- Linux host system (tested on Ubuntu)

### Installation & Usage

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd InfiniteRadio
   ```

2. **Build the Docker image:**
   ```bash
   cd MusicContainer
   docker build -t musicbeats .
   ```

3. **Run the system:**
   ```bash
   ../run_server.sh
   ```

4. **Access the web interface:**
   - Open your browser and navigate to `http://localhost:8080`
   - Click the play button to start streaming
   - Select genres manually or let the Process DJ handle it automatically

### Running the Process DJ

To enable automatic genre switching based on your running applications:

```bash
# Run the Process DJ (outside the container)
python process_dj.py localhost 8080
```

The Process DJ will monitor your system and automatically change music genres based on what applications are most active.

## API Reference

### Change Genre

**POST** `/genre`

```bash
curl -X POST http://localhost:8080/genre \
  -H "Content-Type: application/json" \
  -d '{"genre": "jazz"}'
```

### Get Current Genre

**GET** `/current-genre`

```bash
curl http://localhost:8080/current-genre
```

## Manual Docker Usage

If you prefer to run without the script:

```bash
# Get your host IP
HOST_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)192\.168\.\d+\.\d+' | head -1)

# Run the container
docker run --rm \
  --gpus all \
  --network host \
  -e HOST_IP=$HOST_IP \
  musicbeats
```

### Building from Source

The Docker build process:
1. Installs CUDA runtime and development tools
2. Sets up Python 3.10 with required packages
3. Installs Magenta Realtime with GPU support
4. Builds Go WebRTC server
5. Pre-downloads AI models for faster startup

