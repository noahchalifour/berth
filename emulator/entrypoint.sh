#!/usr/bin/env bash
# Boots one emulator for one lease. Configured entirely by env (set by the hub):
#   SYSTEM_IMAGE  sdkmanager package, e.g. system-images;android-35;google_apis;x86_64
#   DEVICE        avdmanager device id, e.g. pixel_8
#   RAM_MB, CORES
set -euo pipefail

if [[ ! -w /dev/kvm ]]; then
  echo "FATAL: /dev/kvm missing or not writable. The Pod must request squat.ai/kvm and run on an emulator-hub/kvm=true node." >&2
  exit 3
fi

IFS=';' read -r _ _ tag abi <<<"$SYSTEM_IMAGE"
echo no | avdmanager create avd --force --name lease --package "$SYSTEM_IMAGE" \
  --tag "$tag" --abi "$abi" --device "$DEVICE" >/dev/null

# adbd: the emulator binds 127.0.0.1:5555 only; socat publishes it on the Pod
# IP as :5555 via port 5557 -> see Service targetPort. gRPC (-grpc) already
# listens on all interfaces.
socat TCP-LISTEN:5557,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:5555 &

exec emulator -avd lease \
  -no-window -no-audio -no-boot-anim -no-snapshot -wipe-data \
  -gpu swiftshader_indirect -accel on \
  -memory "$RAM_MB" -cores "$CORES" \
  -ports 5554,5555 \
  -grpc 8554 \
  -skip-adb-auth
