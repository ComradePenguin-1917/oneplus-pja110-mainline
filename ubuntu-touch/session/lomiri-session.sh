#!/bin/sh
# Lomiri session launcher for PJA110 on mainline Mir.
#
# This is the piece noble's packaging does not provide: there is no
# lomiri-session binary and no systemd --user unit for the shell, so the session
# has to set up the environment Miri/Lomiri expect and exec the shell on the
# gbm-kms backend.
#
# It is written to be usable both from a chroot test and, later, from a real
# systemd user session: everything it needs comes from the environment.
#
#   lomiri-session.sh [--test-seconds N]
#
# Environment:
#   XDG_RUNTIME_DIR       required; created 0700 if missing
#   LOMIRI_MIR_PLATFORM   defaults to mir:gbm-kms
#   LOMIRI_MIR_RENDERER   defaults to mir:egl-generic
set -eu

TEST_SECONDS=""
if [ "${1:-}" = "--test-seconds" ]; then
    TEST_SECONDS=${2:?}
fi

: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
export XDG_RUNTIME_DIR
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

# Mir server options must go through the environment: lomiri's own option
# parser rejects them on the command line.
export MIR_SERVER_PLATFORM_DISPLAY_LIBS=${LOMIRI_MIR_PLATFORM:-mir:gbm-kms}
export MIR_SERVER_PLATFORM_RENDERING_LIBS=${LOMIRI_MIR_RENDERER:-mir:egl-generic}
export MIR_SERVER_PLATFORM_PATH=${MIR_SERVER_PLATFORM_PATH:-/usr/lib/aarch64-linux-gnu/mir/server-platform}

# Qt clients (including Lomiri's own QML) talk to Mir through this QPA plugin.
export QT_QPA_PLATFORM=ubuntumirclient
export QT_QPA_PLATFORM_PLUGIN_PATH=${QT_QPA_PLATFORM_PLUGIN_PATH:-/usr/lib/aarch64-linux-gnu/qt5/plugins/platforms}

# Keep the default reports quiet; uncomment for debugging.
# export MIR_SERVER_DISPLAY_REPORT=log
# export MIR_SERVER_INPUT_REPORT=log

if [ -n "$TEST_SECONDS" ]; then
    exec timeout "$TEST_SECONDS" /usr/bin/lomiri
fi
exec /usr/bin/lomiri
