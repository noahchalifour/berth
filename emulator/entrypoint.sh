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

# adb identity: -skip-adb-auth relies on the emulator pushing an adb public
# key into the guest via the ro.boot.qemu.adb.pubkey kernel property, which a
# guest oneshot service (ranchu-adb-setup) writes to /data/misc/adb/adb_keys
# on first boot -- see device/generic/goldfish/init.ranchu.adb.setup.sh in
# AOSP. Both the emulator process and any "adb" client it shells out to
# internally (visible in the boot log: "adb -s emulator-5554 shell settings
# put ...") resolve their own signing identity the same way upstream adb
# does (adb_get_android_dir_path(), see packages/modules/adb/adb_utils.cpp):
# $HOME/.android/adbkey, generated on demand if missing. With -wipe-data and
# a from-scratch AVD, nothing pins that file down, so it's regenerated
# per-boot -- and if two of the several adb calls this entrypoint/the
# emulator make race against that regeneration, they can end up presenting
# a key that was never the one seeded into the guest via
# ro.boot.qemu.adb.pubkey. That race is apparently harmless for the
# google_apis/pixel image (real GitHub Actions/KVM run: clean, immediate
# auth) but is fatal for android-tv, where every adb client without the
# exact matching key -- including the emulator's own internal calls -- is
# rejected: "device unauthorized. This adb server's $ADB_VENDOR_KEYS is not
# set". Generating the key once, up front, before the emulator (and thus
# ranchu-adb-setup) ever runs removes that race, and ADB_VENDOR_KEYS is set
# too so any adb invocation that still looks elsewhere first also finds and
# trusts it. The CI workflow copies this same key out for the external
# `adb connect` step so it presents the identical, pre-authorized identity.
# This is purely additive -- one stable trusted key instead of a possibly
# regenerated one -- so it should not affect the already-working
# pixel_8/android-35 path.
mkdir -p "$HOME/.android"
[[ -f "$HOME/.android/adbkey" ]] || adb keygen "$HOME/.android/adbkey"
export ADB_VENDOR_KEYS="$HOME/.android/adbkey"

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
