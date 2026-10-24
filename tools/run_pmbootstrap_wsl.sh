#!/bin/bash
# Run as the ordinary WSL user in an interactive terminal; pmbootstrap requests sudo itself.
#
# For fully non-interactive builds the caller may set PMB_AS_ROOT=1 and start
# this script as root inside a private mount namespace.  pmbootstrap then gets
# --as-root and never calls sudo; this is the supported way to build without an
# interactive password and it only touches the WSL build chroot, never the phone.
set -euo pipefail
PMB_GLOBAL=()
if [ "${PMB_AS_ROOT:-0}" = 1 ]; then
 if [ "$(id -u)" != 0 ]; then
  echo 'PMB_AS_ROOT=1 requires starting this script as root.' >&2
  exit 1
 fi
 PMB_GLOBAL+=(--as-root)
elif [ "$(id -u)" = 0 ]; then
 echo 'Run this script as your ordinary WSL user, without prefixing the script with sudo.'
 exit 1
fi
if [ "${PMB_OFFLINE:-0}" = 1 ]; then
 # Use the already populated apk cache; no mirror access from the build host.
 PMB_GLOBAL+=(--offline)
fi
ROOT="$HOME/workspace/PJA110-Mainline"
WIN=/mnt/h/workspace/PJA110-Mainline
OUT="$WIN/out/pmbootstrap-wsl-probe-20261015"
export PYTHONPATH="$OUT/python-deps${PYTHONPATH:+:$PYTHONPATH}"
test -f "$ROOT/pmbootstrap-pja110.cfg"
test -f "$ROOT/pmaports/device/testing/device-oneplus-xigua/APKBUILD"
mkdir -p "$OUT"
pmb() {
 python3 "$ROOT/pmbootstrap/pmbootstrap.py" \
  -c "$ROOT/pmbootstrap-pja110.cfg" -p "$ROOT/pmaports" \
  -w "$ROOT/pmbootstrap-work" -j 8 "${PMB_GLOBAL[@]}" "$@"
}
stage=${1:-probe}
case "$stage" in
 probe)  pmb chroot --output stdout -- /bin/sh -ec 'if [ -f /etc/os-release ]; then cat /etc/os-release; else echo "Minimal build chroot: /etc/os-release absent"; fi; apk --version; test -d /proc/self; test -r /proc/self/mountinfo; echo PMBOOTSTRAP_NATIVE_CHROOT_PASS' 2>&1 | tee "$OUT/chroot-probe.log"
  ;;
 device)
  pmb build device-oneplus-xigua 2>&1 | tee "$OUT/build-device.log"
  ;;
 kernel)
  pmb build firmware-oneplus-xigua-adreno 2>&1 | tee "$OUT/build-firmware.log"
  pmb build linux-oneplus-xigua 2>&1 | tee "$OUT/build-kernel.log"
  pmb build device-oneplus-xigua 2>&1 | tee "$OUT/build-device.log"
  ;;
 phoc)
  # Local recipe based on Alpine; never overwrite an unrelated checkout change.
  src="$WIN/postmarketos/main/phoc"
  dst="$ROOT/pmaports/main/phoc"
  if [ -e "$dst" ]; then
   diff -r "$src" "$dst"
  else
   mkdir -p "$ROOT/pmaports/main"
   cp -a "$src" "$dst"
  fi
  # crossdirect failed during Meson's GCC preprocessor probe (missing cc1).
  # Use pmbootstrap's supported QEMU-only backend, retaining the Alpine recipe.
  # Preserve the previous attempt before tee truncates the log.
  if [ -f "$OUT/build-phoc-aarch64.log" ]; then
   cp -p "$OUT/build-phoc-aarch64.log" "$OUT/build-phoc-aarch64-$(date +%Y%m%d-%H%M%S).log"
  fi
  pmb --no-cross build --arch aarch64 phoc 2>&1 | tee "$OUT/build-phoc-aarch64.log"
  ;;
 integrated)
  python3 "$WIN/tools/prepare_pmos_integrated_build.py"
  # Reuse unchanged firmware/kernel/Phoc APKs when already built.
  # Keep the proven cross-native kernel recipe; only Phoc needs QEMU-only mode.
  for package in firmware-oneplus-xigua-adreno firmware-oneplus-xigua-adsp firmware-oneplus-xigua-wifi linux-oneplus-xigua device-oneplus-xigua phoc; do
   if [ "$package" = phoc ]; then
    pmb --no-cross build --arch aarch64 "$package" 2>&1 | tee "$OUT/build-integrated-$package.log"
   else
    pmb build --arch aarch64 "$package" 2>&1 | tee "$OUT/build-integrated-$package.log"
   fi
  done
  python3 "$WIN/tools/prepare_pmbootstrap_mkinitfs_serial.py"
  additions=$(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print(",".join(k+"="+v for k,v in p["packages"].items()))' "$WIN/postmarketos/integration-profile.json")
  # No --sdcard, flasher or block-device argument: produce only a host image.
  pmb install --add "$additions" 2>&1 | tee "$OUT/build-integrated-rootfs.log"
  pmb export 2>&1 | tee "$OUT/export-integrated.log"
  python3 "$WIN/tools/verify_pmos_integrated_image.py" 2>&1 | tee "$OUT/verify-integrated-image.log"
  ;;
 baseline)
  # Rebuild only the recipes that changed for the packaged baseline and keep the
  # existing native buildroot (--lax), instead of re-downloading or zapping it.
  python3 "$WIN/tools/prepare_pmos_integrated_build.py"
  for package in linux-oneplus-xigua device-oneplus-xigua; do
   pmb build --lax --arch aarch64 "$package" 2>&1 | tee "$OUT/build-baseline-$package.log"
  done
  bash "$0" baseline-image
  ;;
 baseline-image)
  # Install/export/verify only: the APKs from the baseline stage are reused.
  # pmbootstrap asks for the target user's password interactively; in a
  # non-interactive build pass PMB_USER_PW (a random one is generated and
  # printed otherwise, and the resulting image is for offline verification).
  pw=${PMB_USER_PW:-}
  if [ -z "$pw" ]; then
   pw=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 20)
   echo "NOTE: PMB_USER_PW unset; generated one-time target password: $pw"
  fi
  python3 "$WIN/tools/prepare_pmbootstrap_mkinitfs_serial.py"
  additions=$(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print(",".join(k+"="+v for k,v in p["packages"].items()))' "$WIN/postmarketos/integration-profile.json")
  pmb install --add "$additions" --password "$pw" 2>&1 | tee "$OUT/build-baseline-rootfs.log"
  pmb export 2>&1 | tee "$OUT/export-baseline.log"
  python3 "$WIN/tools/verify_pmos_integrated_image.py" 2>&1 | tee "$OUT/verify-baseline-image.log"
  python3 "$WIN/tools/archive_pmos_integrated_image.py" --force 2>&1 | tee "$OUT/archive-baseline-image.log"
  # Keep the exact APKs that were installed next to their verification report.
  for pkg in linux-oneplus-xigua device-oneplus-xigua; do
   ver=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["packages"][sys.argv[2]])' "$WIN/postmarketos/integration-profile.json" "$pkg")
   cp "$ROOT/pmbootstrap-work/packages/edge/aarch64/$pkg-$ver.apk" "$WIN/out/baseline-20261017/"
  done
  python3 "$WIN/tools/inspect_baseline_apks.py" 2>&1 | tee "$OUT/inspect-baseline-apks.log"
  ;;
 rootfs)
  # Narrow diagnostic workaround for the observed ARM64 Go GC crash under QEMU.
  python3 "$WIN/tools/prepare_pmbootstrap_mkinitfs_serial.py"
  # install without --sdcard writes only an image in this isolated work directory.
  pmb install 2>&1 | tee "$OUT/build-rootfs.log"
  pmb export 2>&1 | tee "$OUT/export.log"
  ;;
 *) echo 'Usage: bash run_pmbootstrap_wsl.sh probe|kernel|device|phoc|rootfs|integrated|baseline|baseline-image' >&2; exit 2 ;;
esac
