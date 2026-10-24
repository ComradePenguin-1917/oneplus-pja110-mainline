#!/bin/busybox ash
# Diagnostic init: no mounts, no install. Prints what it sees, then reboots.
# Used to establish whether the kernel executes /init at all, independently of
# the display: if the device reboots ~30 s after power-on, this ran.

echo "PROBE: init is running"
echo "PROBE: pid=$$"
echo "PROBE: shell=$0"
echo "PROBE: tty0=$([ -c /dev/tty0 ] && echo yes || echo no)"
echo "PROBE: console=$([ -c /dev/console ] && echo yes || echo no)"
echo "PROBE: proc=$([ -d /proc/self ] && echo mounted || echo not-mounted)"
echo "PROBE: /dev entries:"
ls -l /dev 2>&1 | head -25
echo "PROBE: /proc/cmdline:"
cat /proc/cmdline 2>&1
echo "PROBE: sleeping 30s, then rebooting"
sleep 30
echo "PROBE: rebooting now"
reboot -f
sleep 300
