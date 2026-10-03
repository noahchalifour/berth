"""Boot the emulator in kind as the hub's own Pod manifest, then with one
aspect removed at a time, to find what stops it booting in-cluster.
    uv run python e2e/bisect-pod.py <context> <image>
Prints one line per variant: booted in Ns / hung / exited."""

import json
import subprocess
import sys
import time

from emulator_hub.models import Profile
from emulator_hub.pods import build_pod

ctx, image = sys.argv[1], sys.argv[2]
profile = Profile("diag", "phone", "android-35-google-apis", "medium_phone", 2048, 2)


def kubectl(*args, input=None, check=True):
    return subprocess.run(["kubectl", "--context", ctx, "-n", "emulator-hub", *args], input=input, text=True,
                          capture_output=True, check=check).stdout  # fmt: skip


def variant(name, mutate):
    lease = f"diag{name}".ljust(8, "x")
    pod = build_pod(namespace="emulator-hub", image=image, slot=9, lease_id=lease, profile=profile)
    pod["metadata"]["name"] = f"diag-{name}"
    pod["metadata"]["labels"]["app.kubernetes.io/name"] = "diag"
    mutate(pod)
    kubectl("apply", "-f", "-", input=json.dumps(pod))
    start, result = time.time(), "timeout"
    while time.time() - start < 420:
        logs = kubectl("logs", pod["metadata"]["name"], check=False)
        phase = json.loads(kubectl("get", "pod", pod["metadata"]["name"], "-o", "json"))["status"].get("phase")
        if "Boot completed" in logs:
            result = f"booted in {time.time() - start:.0f}s"
            break
        if phase in ("Failed", "Succeeded"):
            result = f"exited ({phase})"
            break
        time.sleep(5)
    hangs = logs.count("hanging thread")
    top = kubectl("top", "pod", pod["metadata"]["name"], check=False).strip().splitlines()[-1:]
    print(f"{name:24} {result:18} hanging-thread={hangs} {top}", flush=True)
    kubectl("delete", "pod", pod["metadata"]["name"], "--grace-period=0", "--force", check=False)


c = lambda p: p["spec"]["containers"][0]  # noqa: E731
variants = {
    "as-built": lambda p: None,
    "no-mem-limit": lambda p: c(p)["resources"]["limits"].pop("memory"),
    "no-cpu-request": lambda p: c(p)["resources"]["requests"].pop("cpu"),
    "no-securitycontext": lambda p: c(p).pop("securityContext"),
    "no-emptydir": lambda p: (p["spec"].pop("volumes"), c(p).pop("volumeMounts")),
    "privileged": lambda p: c(p).__setitem__("securityContext", {"privileged": True}),
}
only = sys.argv[3:] or list(variants)
for name in only:
    variant(name, variants[name])
