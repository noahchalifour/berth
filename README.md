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
`uv run pytest` runs the unit and integration suite. `./scripts/gen-grpc.sh` regenerates the
gRPC/protobuf bindings in `src/emulator_hub/_grpc` from `proto/`.

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

- `ghcr.io/noahchalifour/emulator-hub` — the hub server (MCP + HTTP API + live
  view), built from the repo root `Dockerfile`.
- `ghcr.io/noahchalifour/emulator-hub-emulator` — the Android emulator image
  each slot runs, built from `emulator/Dockerfile`.

## Deploy

Deployment manifests live outside this repo, in
[`kubernetes/apps/emulator-hub/`](https://github.com/noahchalifour/home-lab-infrastructure/tree/main/kubernetes/apps/emulator-hub)
in `noahchalifour/home-lab-infrastructure`.

### adb on Android TV

`android-tv` system images are `user` builds: adbd trusts only the key that
the emulator pushes into the guest at boot, so a client key the device has
never seen stays `unauthorized`. To make TV usable, give the hub one key pair
for every emulator:

```bash
adb keygen adbkey   # writes adbkey and adbkey.pub
kubectl -n emulator-hub create secret generic emulator-hub-adb-key \
  --from-file=adbkey --from-file=adbkey.pub
```

Mount that Secret into the hub and set `HUB_ADB_KEY_DIR` to the mount path.
Every emulator then trusts that key. Bearer-token holders can download it from
`GET /adbkey` on the machine port, and each lease grant carries
`adb_key_url: "/adbkey"`. The MCP instructions tell agents to install it as
`~/.android/adbkey` before `adb connect`.

The hub passes the key to each emulator Pod as an env var, so anyone who can
read Pods in the namespace can read it too. The trade-off: anyone with the API
token can reach any leased device over adb.
That is the same trust boundary as today, where locking is cooperative. Without
`HUB_ADB_KEY_DIR` nothing changes: phone and tablet images still accept any
client key, and TV does not.

## Fonts

The web UI vendors [Inter](https://github.com/rsms/inter) and
[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) under
`src/emulator_hub/ui/fonts/`, both licensed under the SIL Open Font License
1.1.
