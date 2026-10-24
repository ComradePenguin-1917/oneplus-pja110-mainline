#!/bin/bash
# Run from an ordinary user's interactive WSL terminal.
# Root is used only to create a private mount namespace; pmbootstrap runs as the user.
set -euo pipefail
if [ "$(id -u)" = 0 ]; then
 echo 'Run without sudo; this launcher requests the required privileges itself.' >&2
 exit 1
fi
stage=${1:-kernel}
case "$stage" in probe|kernel|device|phoc|rootfs|integrated|baseline) ;; *) echo 'Usage: bash run_pmbootstrap_isolated.sh probe|kernel|device|phoc|rootfs|integrated|baseline' >&2; exit 2 ;; esac
runner=/mnt/h/workspace/PJA110-Mainline/tools/run_pmbootstrap_wsl.sh
test -r "$runner"
for tool in sudo unshare runuser; do command -v "$tool" >/dev/null; done
echo 'Creating a private build mount namespace; pmbootstrap will run as your ordinary user.'
sudo -v
exec sudo unshare --mount --propagation private -- \
 runuser -u "$(id -un)" -- env HOME="$HOME" PATH="$PATH" \
 bash "$runner" "$stage"
