# End-to-end suite

`tests/e2e` drives the deployed service only the way its users do: MCP over
streamable HTTP through the MCP Ingress, REST and the live-view WebSocket through
ingress-nginx and (fake) authentik forward-auth, and `adb connect` to a slot's
LoadBalancer IP. `kubectl` and `docker exec` on the kind nodes are used only to
observe and to inject faults.

## What gets deployed (`e2e/up.sh`)

| Piece | Stands in for |
|---|---|
| kind, 3 nodes: control plane, `e2e/role=hub` worker, `emulator-hub/kvm=true` worker | the home-lab cluster |
| `/dev/kvm` on the KVM node, `0660 root:993` | the pve4 workers |
| squat/generic-device-plugin advertising `squat.ai/kvm` | the same plugin in prod |
| MetalLB L2 pool + `slot-N` LoadBalancer Services | the slot LAN IPs |
| ingress-nginx with `auth-url` + `auth-response-headers` to a fake authentik (cookie `e2e_user`) | authentik forward-auth |
| NetworkPolicies (kindnet enforces them) | the prod policies |
| hub Deployment (Recreate, PVC on a hostPath shared by both workers), Role with pods create/delete/get/list | the prod Deployment |
| `e2e-client` (MCP allowed) and `e2e-scratch` (denied) namespaces with a toolbox Pod | in-cluster agents and strangers |

`E2E_EMULATOR` picks the emulator image the hub boots:

- `real`: `emulator/Dockerfile`, real Android under KVM. Needs Linux/x86_64 with `/dev/kvm`.
- `fake` (the default without KVM): `e2e/fake-emulator`, a gRPC stand-in that
  speaks the same proto. It honours the `/dev/kvm` exit-3 contract, answers
  `getStatus`, the screenshot RPCs and input RPCs, logs every input event, and
  answers the adb port with its Pod name. Built in modes `ok`, `slow` (75s
  boot), `never-boots` and `exit-during-boot`, so the failure paths stay
  deterministic.

Tests that need Android itself (adb shell, APK installs, real key events) are
marked `real_emulator` and skip on the fake. Tests that read the fake's event
log are marked `fake_only`. Everything else runs on both.

## Run it

```bash
./e2e/up.sh                            # build images, create/refresh the cluster (~5 min first time)
./e2e/run.sh                           # whole suite
./e2e/run.sh tests/e2e/test_queue.py   # one file
./e2e/run.sh tests/e2e -k lifecycle -x # pytest args as usual
./e2e/down.sh                          # delete the cluster
```

`run.sh` runs pytest in a runner container (Playwright, adb, kubectl, Node and
the TypeScript MCP SDK) joined to the `kind` Docker network, so slot IPs and
the ingress resolve the same way on Linux CI and on macOS (colima or Docker
Desktop). On a Linux host with KVM, `up.sh` picks the real emulator. On a Mac
it uses the fake, and the real-emulator tests skip.

On failure, every test dumps hub logs, emulator Pod logs, namespace events and
`describe` output to `e2e/.state/artifacts/<test>/`. Set
`E2E_ARTIFACTS_ALWAYS=1` to keep them for passing tests too. CI uploads that
directory.

After every test an invariant check releases whatever is left and requires a
settled hub: every slot free, queue empty, no active lease, no emulator Pod.

## Expected failures

Defects the suite finds are committed as `xfail(strict=True)` with the reason,
so a fix that makes one pass turns the run red until the marker is removed.
There are none right now. The first batch was fixed in the PR after the one
that introduced the suite.

## The emulator image contract

`tests/e2e/test_image.py` runs under plain Docker, with no cluster. The
`emulator-image` job in `build.yml` runs it once per catalog device:

```bash
docker build -t emulator:ci emulator/
E2E_IMAGE=emulator:ci E2E_SYSTEM_IMAGE='system-images;android-35;google_apis;x86_64' E2E_DEVICE=pixel_8 \
  uv run --group e2e pytest tests/e2e/test_image.py -m e2e -o addopts=
```

## Test APK

`e2e/test-apk/e2e-probe.apk` (committed) is a one-activity app that logs
touches, keys and text under logcat tag `E2E`. Rebuild it with
`ANDROID_HOME=... e2e/test-apk/build.sh` (needs `build-tools` and
`platforms;android-35`, no Gradle).
