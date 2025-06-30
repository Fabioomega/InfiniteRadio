# ChobinBeats

## Prerequisites

- Docker
- NVIDIA GPU with CUDA support
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

## Running

1. Build the Docker image:
```bash
docker build -t chobinbeats .
```

2. Run the container:
```bash
./run_server.sh
```

3. Access the web interface at `http://localhost:8080`

## API

### Change Genre

**POST** `/genre`

```bash
curl -X POST http://localhost:8080/genre \
  -H "Content-Type: application/json" \
  -d '{"genre": "jazz"}'
```

Example preset genres:
- synthwave
- disco funk
- cello
- jazz
- rock
- classical
- ambient
- electronic
- hip hop
- reggae
- country
- blues

**Custom genres are also supported!** You can send any text description:
```bash
curl -X POST http://localhost:8080/genre \
  -H "Content-Type: application/json" \
  -d '{"genre": "dark techno with heavy bass"}'
```

## Manual Docker Run

If you prefer not to use the script:

```bash
docker run --rm \
  --gpus all \
  --network host \
  -e HOST_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)192\.168\.\d+\.\d+' | head -1) \
  chobinbeats
```