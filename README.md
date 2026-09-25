# emulator-hub

A lease-based pool of self-hosted Android emulators. Agents (and humans) check
out a slot through an MCP server or a small HTTP API, get exclusive use of a
running emulator for a bounded lease, and release it (or let it expire) back
to the pool; a live-view web UI lets a human watch or take over any active
session.

## Develop

```bash
uv sync
uv run pytest
./scripts/gen-grpc.sh
```

`uv sync` installs the runtime and dev dependency groups into `.venv/`.
`uv run pytest` runs the test suite. `./scripts/gen-grpc.sh` regenerates the
gRPC/protobuf bindings in `src/emulator_hub/_grpc` from `proto/`.

## Images

Two images are published to GHCR, tagged only on `v*` release tags (no
`latest`, no per-commit tags):

- `ghcr.io/noahchalifour/emulator-hub` — the hub server (MCP + HTTP API + live
  view), built from the repo root `Dockerfile`.
- `ghcr.io/noahchalifour/emulator-hub-emulator` — the Android emulator image
  each slot runs, built from `emulator/Dockerfile`.

## Deploy

Deployment manifests live outside this repo, in
[`kubernetes/apps/emulator-hub/`](https://github.com/noahchalifour/home-lab-infrastructure/tree/main/kubernetes/apps/emulator-hub)
in `noahchalifour/home-lab-infrastructure`.
