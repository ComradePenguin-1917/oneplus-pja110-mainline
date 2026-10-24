"""Use logind for a native reboot and verify authenticated SSH recovery."""
import json
import subprocess
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'out/native-install-20261016/first-native-boot'
OUT = BASE/('reboot-'+time.strftime('%Y%m%d-%H%M%S'))
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'none', '-T', '-i',
       str(ROOT/'out/usb-ncm-20261013/ssh/client_key_host'), '-o', 'BatchMode=yes',
       '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o',
       f'UserKnownHostsFile={BASE/"known_hosts"}', '-o', 'ConnectTimeout=4', 'penguin@172.16.42.1']
CMD = 'cat /proc/sys/kernel/random/boot_id; uname -r; cat /proc/1/comm; findmnt /; findmnt /boot; systemctl is-system-running; systemctl --failed --no-pager; pgrep -a phoc; pgrep -a phosh'

def read(cmd, timeout=12):
    return subprocess.run(SSH+[cmd], capture_output=True, timeout=timeout)

OUT.mkdir(parents=True)
before = read(CMD)
before.check_returncode()
assert b'6.14.0-oneplus-xigua' in before.stdout and b'\nsystemd\n' in before.stdout
boot_id = before.stdout.splitlines()[0]
(OUT/'before.txt').write_bytes(before.stdout+before.stderr)
if '--observe' not in sys.argv:
    request = read('busctl --allow-interactive-authorization=yes call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager Reboot b true', 60)
    (OUT/'request.txt').write_bytes(request.stdout+request.stderr)
    if request.returncode and b'Connection' not in request.stderr:
        print(request.stderr.decode(errors='replace'), flush=True)
        raise SystemExit('Reboot authorization did not complete; system was not declared rebooted')
else:
    print('Baseline captured; observing a user-requested desktop reboot', flush=True)
started = time.monotonic()
while time.monotonic()-started < 150:
    time.sleep(4)
    try:
        current = read(CMD)
    except subprocess.TimeoutExpired:
        continue
    if current.returncode or not current.stdout:
        continue
    if current.stdout.splitlines()[0] == boot_id:
        continue
    (OUT/'after.txt').write_bytes(current.stdout+current.stderr)
    if b'\nrunning\n' not in current.stdout or b'0 loaded units listed' not in current.stdout:
        continue
    assert b'6.14.0-oneplus-xigua' in current.stdout and b'\nsystemd\n' in current.stdout
    assert b'/dev/loop0p2 ext4' in current.stdout
    result = {'native_reboot_ssh_verified': True, 'seconds_to_observe_recovery': round(time.monotonic()-started, 1), 'before_boot_id': boot_id.decode(), 'after_boot_id': current.stdout.splitlines()[0].decode(), 'failed_units': 0, 'display_touch_visual_retest_pending': True}
    (OUT/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2), flush=True)
    break
else:
    raise SystemExit('Native reboot recovery not verified within 150 seconds; inspect USB before another reboot')
