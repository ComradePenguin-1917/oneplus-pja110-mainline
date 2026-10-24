"""Bounded runtime display checks; never write partitions."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/display-port-20261013'
GENERATED = '--generated' in sys.argv
LOG = (ROOT / 'out/display-generator-avb-retest-20261014' if GENERATED else OUT) / 'runtime-validation'
LOG.mkdir(exist_ok=True)
KEYS = ROOT / 'out/usb-ncm-20261013/ssh'
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'none', '-T', '-i',
       str(KEYS / 'client_key_host'), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
       '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={KEYS/"known_hosts"}',
       '-o', 'ConnectTimeout=3', '-o', 'ServerAliveInterval=5', 'root@169.254.42.1']


def remote(cmd, data=None, timeout=15):
    return subprocess.run(SSH + [cmd], input=data, capture_output=True, timeout=timeout)


def checked(cmd, data=None, timeout=15):
    p = remote(cmd, data, timeout)
    if p.returncode:
        print(p.stderr.decode(errors='replace'), flush=True)
        p.check_returncode()
    return p.stdout


def upload_pattern():
    data = (OUT / 'fb-pattern').read_bytes()
    response = checked('cat > /tmp/fb-pattern; chmod 700 /tmp/fb-pattern; sha256sum /tmp/fb-pattern', data)
    assert response.decode().split()[0] == hashlib.sha256(data).hexdigest()


mode = sys.argv[1]
identity = checked('uname -a; cat /proc/sys/kernel/random/boot_id; cat /proc/uptime')
if GENERATED:
    assert b'AA536 generator-based 60Hz driver' in checked('dmesg')
    manifest=json.loads((LOG.parent/'deployment-manifest.json').read_text())
    assert manifest['phone_execution_confirmed'] and manifest['other_seven_boot_partitions_unchanged']
else:
    assert b'#14 SMP' in identity, 'Only test the validated GPIO90 display build'
expected_uname=identity.splitlines()[0]
(LOG / f'{mode}-before.txt').write_bytes(identity)
if mode in ('brightness', 'cycles'):
    upload_pattern()
    if mode == 'brightness':
        script = '''set -e
b=/sys/class/backlight/ae94000.dsi.0
test -f "$b/brightness"
old=$(cat "$b/brightness")
trap 'echo "$old" > "$b/brightness"' EXIT HUP INT TERM
/tmp/fb-pattern
for value in 64 128 512 1024 128; do
  echo "$value" > "$b/brightness"
  printf 'BRIGHTNESS requested=%s actual=' "$value"
  cat "$b/actual_brightness"
  sleep 6
done
'''
    else:
        script = '''set -e
grep -q ' /sys/kernel/debug debugfs ' /proc/mounts || mount -t debugfs debugfs /sys/kernel/debug
trap '/tmp/fb-pattern --unblank' EXIT HUP INT TERM
for i in 1 2 3 4 5; do
  echo "CYCLE $i OFF"
  /tmp/fb-pattern --blank
  cat /sys/kernel/debug/gpio | grep 'gpio90  : out low'
  sleep 2
  echo "CYCLE $i ON"
  /tmp/fb-pattern --unblank
  cat /sys/kernel/debug/gpio | grep 'gpio90  : out high'
  /tmp/fb-pattern
  sleep 3
done
'''
    with (LOG / f'{mode}-output.txt').open('wb') as log:
        p = subprocess.Popen(SSH + [script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for line in p.stdout:
                log.write(line)
                log.flush()
                print(line.decode(errors='replace'), end='', flush=True)
            if p.wait(timeout=10):
                raise SystemExit(p.returncode)
        finally:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=10)
    (LOG / f'{mode}-dmesg.txt').write_bytes(checked('dmesg'))
    (LOG / f'{mode}-result.json').write_text(json.dumps({'software_check_passed': True,
        'visual_confirmation_required': True}, indent=2) + '\n')
    print(f'PASS: {mode} software checks; physical screen observation required', flush=True)
elif mode == 'reboot':
    before_id = identity.splitlines()[1]
    started = time.monotonic()
    try:
        p = remote('reboot -f', timeout=10)
        (LOG / 'reboot-request.txt').write_bytes(p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        pass  # A connection drop during reboot is expected; prove reboot by boot_id.
    time.sleep(4)
    while time.monotonic() - started < 100:
        try:
            p = remote('uname -a; cat /proc/sys/kernel/random/boot_id; cat /proc/uptime; cat /sys/class/udc/*/state')
        except subprocess.TimeoutExpired:
            time.sleep(3)
            continue
        if p.returncode == 0 and p.stdout.splitlines()[0] == expected_uname and p.stdout.splitlines()[1] != before_id:
            assert b'configured' in p.stdout
            (LOG / 'reboot-after.txt').write_bytes(p.stdout)
            upload_pattern()
            (LOG / 'reboot-pattern.txt').write_bytes(checked('/tmp/fb-pattern'))
            (LOG / 'reboot-dmesg.txt').write_bytes(checked('dmesg'))
            result = {'boot_id_changed': True, 'same_kernel_build': True,
                      'automatic_ssh_returned': True,
                      'elapsed_seconds': round(time.monotonic() - started, 2),
                      'visual_confirmation_required': True}
            (LOG / 'reboot-result.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result), flush=True)
            break
        time.sleep(3)
    else:
        raise SystemExit('SSH did not return on the expected kernel within 100 seconds; check phone state')
else:
    raise SystemExit('use brightness | cycles | reboot')
