#!/bin/bash
# Non-interactive baseline image build (isolated build host only).
#
#   PMB_AS_ROOT=1        run pmbootstrap with --as-root (no sudo prompts)
#   PMB_USER_PW=...      password for the generated image's user; a random one
#                        is printed when unset (image is for offline inspection)
#   PMB_BUILD_PROXY=...  optional HTTP(S) proxy for the build host, e.g.
#                        http://172.22.32.1:7897 when a Windows proxy is
#                        reachable from WSL
#   PMB_OFFLINE=1        use the existing apk cache only
#
# The phone is never contacted; this only drives the WSL build chroot.
set -e
export PMB_AS_ROOT="${PMB_AS_ROOT:-1}"
export PMB_USER_PW="${PMB_USER_PW:-}"
# The WSL build tree lives under the desktop user's home; do not inherit
# HOME=/root from the root shell that starts this helper.
export HOME="${PMB_BUILD_HOME:-/home/comrade_penguin_desktop}"
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
if [ -n "${PMB_BUILD_PROXY:-}" ]; then
    export http_proxy="$PMB_BUILD_PROXY"
    export https_proxy="$PMB_BUILD_PROXY"
    export HTTP_PROXY="$PMB_BUILD_PROXY"
    export HTTPS_PROXY="$PMB_BUILD_PROXY"
    gw=$(ip route 2>/dev/null | awk '/^default/ {print $3; exit}')
    export no_proxy="localhost,127.0.0.1,${gw:-}"
    export NO_PROXY="$no_proxy"
fi
exec unshare --mount --propagation private -- bash \
    /mnt/h/workspace/PJA110-Mainline/tools/run_pmbootstrap_wsl.sh "${1:-baseline}"
