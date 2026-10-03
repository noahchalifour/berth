#!/usr/bin/env bash
# Boots the emulator image under plain Docker with a given memory cap and
# reports whether and when it booted. Isolates "the Pod's memory limit" from
# "something about kind" when emulators fail to boot in the cluster.
#   e2e/diagnose-boot.sh <image> <memory, e.g. 4096m|none> [RAM_MB] [CORES]
set -uo pipefail
IMAGE=$1 MEM=$2 RAM=${3:-2048} CORES=${4:-2}
NAME=diag-$RANDOM
args=(--device /dev/kvm -d --name "$NAME" -p 127.0.0.1::8554)
[[ $MEM != none ]] && args+=(--memory "$MEM" --memory-swap "$MEM")
docker run "${args[@]}" -e SYSTEM_IMAGE='system-images;android-35;google_apis;x86_64' -e DEVICE=medium_phone \
  -e RAM_MB="$RAM" -e CORES="$CORES" "$IMAGE" >/dev/null
PORT=$(docker port "$NAME" 8554 | head -1 | cut -d: -f2)
start=$(date +%s) result=timeout
while (($(date +%s) - start < 420)); do
  state=$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}' "$NAME")
  if [[ $state == exited* ]]; then result="exited ($state)"; break; fi
  if uv run --frozen python -c "
import asyncio, grpc, sys
from google.protobuf.empty_pb2 import Empty
from emulator_hub._grpc import emulator_controller_pb2_grpc as rpc
async def m():
    async with grpc.aio.insecure_channel('127.0.0.1:$PORT') as ch:
        try: return (await rpc.EmulatorControllerStub(ch).getStatus(Empty(), timeout=5)).booted
        except grpc.aio.AioRpcError: return False
sys.exit(0 if asyncio.run(m()) else 1)" 2>/dev/null; then result="booted in $(($(date +%s) - start))s"; break; fi
  sleep 5
done
echo "mem=$MEM ram=$RAM cores=$CORES: $result; peak $(docker stats --no-stream --format '{{.MemUsage}}' "$NAME" 2>/dev/null)"
grep -c 'hanging thread' <(docker logs "$NAME" 2>&1) | sed 's/^/hanging-thread lines: /'
docker rm -f "$NAME" >/dev/null
