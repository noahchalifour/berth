# Contributing

## Develop

```bash
uv sync
uv run pytest
./scripts/gen-grpc.sh
```

`uv sync` installs the runtime and dev dependency groups into `.venv/`.
`uv run pytest` runs the unit and integration suite. `./scripts/gen-grpc.sh`
regenerates the gRPC/protobuf bindings in `src/emulator_hub/_grpc` from `proto/`.

## End-to-end tests

`tests/e2e` runs the whole service in a kind cluster: real Pods, MetalLB slot
IPs, ingress-nginx with authentik-style forward auth, NetworkPolicies, and (on
Linux with KVM) real Android emulators.

```bash
./e2e/up.sh && ./e2e/run.sh
```

See [`e2e/README.md`](e2e/README.md). CI runs it nightly, on changes to the
suite, and before every release (`.github/workflows/e2e.yml`).

## Images

Two images are published to GHCR, tagged only on `v*` release tags (no
`latest`, no per-commit tags):

- `ghcr.io/noahchalifour/emulator-hub`: the hub server (MCP + HTTP API + live
  view), built from the repo root `Dockerfile`.
- `ghcr.io/noahchalifour/emulator-hub-emulator`: the Android emulator image
  each slot runs, built from `emulator/Dockerfile`.

## Fonts

The web UI vendors [Inter](https://github.com/rsms/inter) and
[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) under
`src/emulator_hub/ui/fonts/`, both licensed under the SIL Open Font License
1.1.

## Screenshots

The README screenshots in `.github/assets/` are captured from the real web UI
running against the in-memory fakes in `tests/fakes.py`, so the device screens
are synthetic.
