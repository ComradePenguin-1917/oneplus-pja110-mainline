"""Verified RAM-only Aston touch switch/capture, with existing-module rollback."""
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ('out/aston-touch-240hz-20261013' if '--rate' in sys.argv else 'out/aston-touch-20261013')
KEYS = ROOT / 'out/usb-ncm-20261013/ssh'
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'none', '-T', '-i', str(KEYS/'client_key_host'),
       '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', f'UserKnownHostsFile={KEYS/"known_hosts"}', '-o', 'ConnectTimeout=5',
       '-o', 'ServerAliveInterval=5', 'root@169.254.42.1']
PARTS = ('boot_a', 'vendor_boot_a', 'init_boot_a', 'dtbo_a',
         'boot_b', 'vendor_boot_b', 'init_boot_b', 'dtbo_b')

def ssh(cmd, data=None, timeout=90):
    p = subprocess.run(SSH + [cmd], input=data, capture_output=True, timeout=timeout)
    (OUT/'last-ssh-stderr.txt').write_bytes(p.stderr)
    p.check_returncode()
    return p.stdout

def hashes():
    raw = ssh('for f in /sys/class/block/sd*/uevent; do cat "$f"; echo END; done')
    devices = {}
    for record in raw.decode().split('END'):
        props = dict(line.split('=', 1) for line in record.splitlines() if '=' in line)
        part = props.get('PARTNAME')
        if part in PARTS:
            assert part not in devices
            assert re.fullmatch(r'sd[a-z]+[0-9]+', props['DEVNAME'])
            devices[part] = props['DEVNAME']
    assert set(devices) == set(PARTS)
    result = {}
    for part, dev in devices.items():
        assert ssh(f"grep '^PARTNAME=' /sys/class/block/{dev}/uevent").decode().strip() == 'PARTNAME='+part
        result[part] = ssh(f'sha256sum /dev/{dev}').decode().split()[0]
    return result

def upload(name):
    data = (OUT/name).read_bytes()
    actual = ssh(f'cat > /tmp/{name}; chmod 700 /tmp/{name}; sha256sum /tmp/{name}', data).decode().split()[0]
    assert actual == hashlib.sha256(data).hexdigest()

mode = sys.argv[1]
if mode == 'flash-autostart':
    assert '--rate' in sys.argv
    auto = json.loads((OUT/'autostart-manifest.json').read_text())
    assert json.loads((OUT/'device-after-ram.json').read_text()) == auto['baseline_hashes']
    qemu = (OUT/'qemu-autostart-console.txt').read_bytes()
    assert b'QEMU touch modules validated' in qemu and b'QEMU debug userspace validated' in qemu
    image = OUT/'init_boot_b-aston-240hz.img'
    assert hashlib.sha256(image.read_bytes()).hexdigest() == auto['init_boot_sha256']
    assert hashlib.sha256((OUT/'synaptics-aston.ko').read_bytes()).hexdigest() == auto['module_sha256']
    assert auto['ssh_identity_and_other_entries_preserved'] and auto['rate_code'] == 3
    def fastboot(args):
        p = subprocess.run(['C:/platform-tools/fastboot.exe', '-s', 'SERIAL'] + args,
                           capture_output=True, timeout=90)
        with (OUT/'fastboot-autostart.log').open('ab') as f:
            f.write(('COMMAND '+ ' '.join(args)+'\n').encode()+p.stdout+p.stderr)
        p.check_returncode()
        result = (p.stdout+p.stderr).decode(errors='replace')
        print(result, flush=True)
        return result
    assert 'current-slot: b' in fastboot(['getvar', 'current-slot'])
    assert 'unlocked: yes' in fastboot(['getvar', 'unlocked'])
    assert 'slot-successful:a: yes' in fastboot(['getvar', 'slot-successful:a'])
    fastboot(['flash', 'init_boot_b', str(image)])
    fastboot(['set_active', 'b'])
    fastboot(['reboot'])
elif mode == 'capture-autostart':
    assert '--rate' in sys.argv
    auto = json.loads((OUT/'autostart-manifest.json').read_text())
    state = ssh('uname -a; cat /proc/sys/kernel/random/boot_id; '
                'cat /tmp/touch-init.log; cat /proc/bus/input/devices; '
                'cat /sys/module/synaptics_aston/parameters/report_rate_code; '
                'cat /proc/interrupts; dmesg')
    (OUT/'autostart-device-after.txt').write_bytes(state)
    assert b'#14 SMP' in state and b'Aston S3910 240Hz touch modules loaded' in state
    assert b'PJA110 Synaptics S3910 (Aston TCM)' in state
    assert b'PJA_ASTON fixed report rate code=3 readback verified' in state
    assert re.search(rb'Level\s+synaptics_tcm', state)
    assert b'Internal error:' not in state and b'Unable to handle kernel' not in state
    actual = hashes()
    assert all(actual[n] == auto['baseline_hashes'][n] for n in PARTS if n != 'init_boot_b')
    assert actual['init_boot_b'] == auto['init_boot_sha256']
    (OUT/'autostart-device-after.json').write_text(json.dumps(actual, indent=2)+'\n')
    auto.update(phone_execution_confirmed=True, automatic_ssh_and_touch_verified=True,
                other_seven_boot_partitions_unchanged=True)
    (OUT/'autostart-manifest.json').write_text(json.dumps(auto, indent=2)+'\n')
    print('PASS: boot automatically loaded Aston code3/level IRQ; image readback and seven other partitions verified')
elif mode == 'preflight':
    assert not (OUT/'device-before.json').exists(), 'Preserve evidence'
    expected = json.loads((ROOT/'out/touch-port-20261013/autostart-device-after.json').read_text())
    actual = hashes()
    assert actual == expected, 'Current device differs from last verified baseline'
    (OUT/'device-before.json').write_text(json.dumps(actual, indent=2)+'\n')
    (OUT/'device-before.txt').write_bytes(ssh('uname -a; cat /proc/bus/input/devices; lsmod; cat /proc/sys/kernel/random/boot_id'))
    assert b'#14 SMP' in (OUT/'device-before.txt').read_bytes()
    print('PASS: all eight partitions match automatic touch/SSH #14 baseline')
elif mode == 'switch':
    assert (OUT/'device-before.json').exists()
    source = json.loads((OUT/'source-manifest.json').read_text())
    for item in source['files']:
        data = (ROOT/source.get('source_directory','drivers/input/touchscreen/synaptics-aston')/item['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['adapted_sha256']
    assert b'LD [M]  synaptics-aston.ko' in (OUT/'build.log').read_bytes()
    upload('synaptics-aston.ko')
    upload('touch-capture-aston')
    (OUT/'switch-before.txt').write_bytes(ssh('lsmod; readlink /sys/bus/spi/devices/spi0.0/driver'))
    try:
        result = ssh('set -e; test -s /lib/modules/mainline_touch_probe.ko; '
                     'rmmod mainline_touch_probe; insmod /tmp/synaptics-aston.ko ' +
                     ('report_rate_code=2; ' if '--code2' in sys.argv else
                      'report_rate_code=3; ' if '--code3' in sys.argv else '; ') +
                     'sleep 2; cat /proc/bus/input/devices; lsmod; '
                     'readlink /sys/bus/spi/devices/spi0.0/driver')
        (OUT/'switch-result.txt').write_bytes(result)
        log = ssh('dmesg')
        (OUT/'switch-dmesg.txt').write_bytes(log)
        assert b'PJA110 Synaptics S3910 (Aston TCM)' in result
        assert b'PJA_ASTON LBP=2 config readback verified' in log
        print('PASS: RAM switch, existing Aston TCM registered input and verified LBP config', flush=True)
        print(result.decode(), flush=True)
    except Exception:
        (OUT/'rollback.txt').write_bytes(ssh('rmmod synaptics_aston 2>/dev/null; '
            'insmod /lib/modules/mainline_touch_probe.ko enable_touch=1; cat /proc/bus/input/devices'))
        raise
elif mode in ('capture', 'capture2', 'capture3', 'capture4', 'capture5', 'capture6', 'capture7', 'capture8'):
    suffix = {'capture': '', 'capture2': '2', 'capture3': '3', 'capture4': '4', 'capture5': '5', 'capture6': '6', 'capture7': '7', 'capture8': '8'}[mode]
    seconds = {'capture': 60, 'capture2': 30, 'capture3': 90, 'capture4': 90, 'capture5': 90, 'capture6': 90, 'capture7': 60, 'capture8': 60}[mode]
    upload('touch-capture-aston')
    # /tmp is cleared by reboot; do not assume the viewer recovery tool exists.
    data = (ROOT/'out/display-port-20261013/fb-pattern').read_bytes()
    actual = ssh('cat > /tmp/fb-pattern; chmod 700 /tmp/fb-pattern; sha256sum /tmp/fb-pattern', data).decode().split()[0]
    assert actual == hashlib.sha256(data).hexdigest()
    ssh('/tmp/fb-pattern')
    path = OUT/f'physical-touch-events{suffix}.txt'
    assert not path.exists(), 'Preserve capture evidence'
    with path.open('wb') as log:
        p = subprocess.Popen(SSH+[f'/tmp/touch-capture-aston --seconds {seconds}'],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for line in p.stdout:
                log.write(line); log.flush()
                if not line.startswith(b'FRAME '):
                    print(line.decode(errors='replace'), end='', flush=True)
            rc = p.wait(timeout=10)
        finally:
            if p.poll() is None: p.terminate(); p.wait(timeout=10)
            ssh('/tmp/fb-pattern')
    text = path.read_text()
    m = re.search(r'SUMMARY frames=(\d+) max_contacts=(\d+)', text)
    assert rc == 0 and m and int(m[1]) > 0, 'No successful physical touch capture'
    (OUT/f'physical-dmesg{suffix}.txt').write_bytes(ssh('dmesg'))
    (OUT/f'physical-result{suffix}.json').write_text(json.dumps({
        'frames': int(m[1]), 'max_contacts': int(m[2]), 'evdev_overflow': 'FAIL evdev overflow' in text,
        'user_observation_pending': True}, indent=2)+'\n')
    print('PASS: captured Aston touch events; awaiting user position/multitouch observation')
elif mode == 'lifecycle':
    log = ssh('set -e; rmmod synaptics_aston; '
              'insmod /lib/modules/mainline_touch_probe.ko enable_touch=1; '
              'cat /proc/bus/input/devices; '
              'rmmod mainline_touch_probe; insmod /tmp/synaptics-aston.ko ' +
              ('report_rate_code=3; ' if '--rate' in sys.argv else '; ') +
              'cat /proc/bus/input/devices; lsmod; dmesg | tail -n 45')
    (OUT/'lifecycle-result.txt').write_bytes(log)
    assert b'PJA110 Synaptics S3910"' in log and b'PJA110 Synaptics S3910 (Aston TCM)' in log
    assert b'Internal error:' not in log and b'Unable to handle kernel' not in log
    print('PASS: Aston unload -> old driver restore -> old unload -> Aston reload; SSH remained available')
elif mode == 'restore':
    print(ssh('set -e; rmmod synaptics_aston; insmod /lib/modules/mainline_touch_probe.ko enable_touch=1; '
              'cat /proc/bus/input/devices').decode())
elif mode == 'fault-reboot':
    fault = OUT/'round1-unload-fault'
    fault.mkdir(exist_ok=True)
    for name in ('synaptics-aston.ko', 'build.log', 'source-manifest.json',
                 'physical-result.json', 'physical-touch-events.txt', 'switch-dmesg.txt'):
        target = fault/name
        assert not target.exists()
        target.write_bytes((OUT/name).read_bytes())
    for item in json.loads((OUT/'source-manifest.json').read_text())['files']:
        target = fault/item['path']
        target.write_bytes((ROOT/'drivers/input/touchscreen/synaptics-aston'/item['path']).read_bytes())
    (fault/'dmesg.txt').write_bytes(ssh('dmesg'))
    before = ssh('cat /proc/sys/kernel/random/boot_id').strip()
    try:
        subprocess.run(SSH+['reboot -f'], capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        print('Normal reboot request timed out; inspect state before further action', flush=True)
        raise SystemExit(2)
    started = time.monotonic()
    while time.monotonic()-started < 75:
        time.sleep(2)
        try:
            result = ssh('uname -a; cat /proc/sys/kernel/random/boot_id; cat /proc/bus/input/devices', timeout=12)
            if before not in result and b'PJA110 Synaptics S3910"' in result:
                (fault/'reboot-recovered.txt').write_bytes(result)
                print('PASS: reboot returned to original automatic touch/SSH #14 baseline', flush=True)
                break
        except (subprocess.SubprocessError, OSError):
            pass
    else:
        raise SystemExit('No original touch/SSH recovery; inspect phone state')
elif mode == 'recover':
    before = ssh('cat /proc/sys/kernel/random/boot_id').strip()
    ssh('test -w /proc/sysrq-trigger')
    try:
        subprocess.run(SSH+['sync; echo b > /proc/sysrq-trigger'], capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        pass
    started = time.monotonic()
    while time.monotonic()-started < 75:
        time.sleep(2)
        try:
            result = ssh('uname -a; cat /proc/sys/kernel/random/boot_id; cat /proc/bus/input/devices', timeout=12)
            if before not in result and b'PJA110 Synaptics S3910"' in result:
                (OUT/'round1-unload-fault/reboot-recovered.txt').write_bytes(result)
                print('PASS: original automatic touch/SSH #14 recovered after emergency restart', flush=True)
                break
        except (subprocess.SubprocessError, OSError):
            pass
    else:
        raise SystemExit('No automatic recovery; manual phone restart needed')
elif mode == 'verify':
    actual = hashes()
    assert actual == json.loads((OUT/'device-before.json').read_text())
    (OUT/'device-after-ram.json').write_text(json.dumps(actual, indent=2)+'\n')
    (OUT/'state-after-ram.txt').write_bytes(ssh('uname -a; cat /proc/uptime; cat /proc/bus/input/devices; lsmod; dmesg | tail -n 50'))
    print('PASS: RAM experiment left all eight boot partitions unchanged')
else:
    raise SystemExit('preflight | switch | capture | restore | verify')
