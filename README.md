Install this: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

docker build -t magenta-rt .

docker run --gpus all -it \
  --device /dev/snd \
  -e PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native \
  -v ${XDG_RUNTIME_DIR}/pulse/native:${XDG_RUNTIME_DIR}/pulse/native \
  -v ~/.config/pulse/cookie:/root/.config/pulse/cookie \
  magenta-rt

