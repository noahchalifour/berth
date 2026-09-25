#!/usr/bin/env bash
# Regenerates src/emulator_hub/_grpc from proto/emulator_controller.proto.
# The proto is copied verbatim from the Android SDK
# ($ANDROID_HOME/emulator/lib/emulator_controller.proto, Apache-2.0).
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m grpc_tools.protoc -Iproto --python_out=src/emulator_hub/_grpc \
  --grpc_python_out=src/emulator_hub/_grpc proto/emulator_controller.proto
# protoc emits a top-level import; make it package-relative.
sed -i.bak 's/^import emulator_controller_pb2/from . import emulator_controller_pb2/' \
  src/emulator_hub/_grpc/emulator_controller_pb2_grpc.py
rm src/emulator_hub/_grpc/*.bak
touch src/emulator_hub/_grpc/__init__.py
