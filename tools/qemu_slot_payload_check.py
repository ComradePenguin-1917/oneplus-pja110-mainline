"""Boot the generated slot-A payload in QEMU and observe a clean systemd start.

Validates only the generic, architecture-independent parts the baseline plan
allows QEMU to cover: the raw arm64 kernel boots, the combined initramfs stream
gives a working early userspace, the exported rootfs reaches systemd, sshd /
NetworkManager / logind become active, and the guest powers off cleanly.

It proves nothing about DSI, touch, ADC, charging, Wi-Fi hardware or UFS slot
management.  The rootfs disk is attached read-only via snapshot=on.
"""
import argparse
import gzip
import hashlib
import json
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from pmos_image_info import inspect_image

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def materialise(image, scratch):
    """Return a raw disk path, decompressing a .gz archive when needed."""
    if image.suffix == '.gz':
        target = Path(scratch) / 'rootfs.img'
        with gzip.open(image, 'rb') as src, target.open('wb') as dst:
            for block in iter(lambda: src.read(4 * 1024 * 1024), b''):
                dst.write(block)
        return target
    return image


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel', default=str(ROOT / 'out/postmarketos-baseline-20261017/vmlinuz'))
    ap.add_argument('--initrd',
                    default=str(ROOT / 'out/native-slot-20261017/existing-root/combined-initrd.lz4'))
    ap.add_argument('--rootfs',
                    default=str(ROOT / 'out/postmarketos-baseline-20261017/oneplus-xigua.img.gz'))
    ap.add_argument('--out', default='out/baseline-20261017/qemu-slot-payload')
    ap.add_argument('--wait', type=int, default=110, help='seconds to let boot settle')
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').unlink(missing_ok=True)
    kernel, initrd, rootfs = Path(args.kernel), Path(args.initrd), Path(args.rootfs)
    for path in (kernel, initrd, rootfs):
        assert path.is_file(), path
    payload = {'kernel': str(kernel), 'kernel_sha256': sha(kernel),
               'initrd': str(initrd), 'initrd_sha256': sha(initrd),
               'rootfs': str(rootfs), 'rootfs_sha256': sha(rootfs)}
    (out / 'payload.json').write_bytes((json.dumps(payload, indent=2) + '\n').encode())

    with tempfile.TemporaryDirectory(prefix='pja110-qemu-') as scratch:
        disk = materialise(rootfs, scratch)
        info = inspect_image(disk)
        (out / 'image-info.json').write_bytes((json.dumps(info, indent=2) + '\n').encode())
        cmdline = (f'console=ttyAMA0 earlycon=pl011,0x9000000 loglevel=4 '
                   f'root=UUID={info["root_uuid"]} rw systemd.log_target=console '
                   'systemd.debug_shell=hvc0 systemd.mask=serial-getty@hvc0.service')
        address = str(Path(scratch) / 'debug.sock')
        argv = ['qemu-system-aarch64', '-machine', 'virt', '-accel', 'tcg', '-cpu', 'max',
                '-smp', '2', '-m', '2048', '-display', 'none',
                '-serial', 'file:' + str(out / 'console.log'), '-monitor', 'none',
                '-no-reboot', '-kernel', str(kernel), '-initrd', str(initrd),
                '-append', cmdline,
                '-drive', f'if=none,id=pmos,file={disk},format=raw,snapshot=on',
                '-device', 'virtio-blk-pci,drive=pmos,logical_block_size=4096,'
                           'physical_block_size=4096',
                '-netdev', 'user,id=net0', '-device', 'virtio-net-pci,netdev=net0',
                '-device', 'virtio-serial-pci', '-chardev',
                f'socket,id=debug,path={address},server=on,wait=off',
                '-device', 'virtconsole,chardev=debug']
        (out / 'command.json').write_bytes((json.dumps(argv, indent=2) + '\n').encode())
        with (out / 'qemu-stderr.log').open('wb') as err:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=err, stderr=err)
            channel = socket.socket(socket.AF_UNIX)
            channel.settimeout(1)
            transcript = bytearray()
            try:
                for _ in range(60):
                    if Path(address).exists():
                        break
                    if proc.poll() is not None:
                        raise SystemExit('QEMU failed to launch; see qemu-stderr.log')
                    time.sleep(1)
                channel.connect(address)

                def receive_until(marker, limit):
                    deadline = time.monotonic() + limit
                    while time.monotonic() < deadline:
                        try:
                            block = channel.recv(65536)
                        except socket.timeout:
                            continue
                        if not block:
                            return False
                        transcript.extend(block)
                        (out / 'debug-console.log').write_bytes(transcript)
                        if marker in transcript:
                            return True
                    return False

                assert receive_until(b'# ', 240), 'diagnostic shell unavailable'
                commands = [
                    'stty -echo', 'export SYSTEMD_COLORS=0 SYSTEMD_PAGER=cat',
                    f'sleep {args.wait}',
                    "printf '\\nPJA110_QEMU_BEGIN\\n'", 'cat /proc/1/comm', 'uname -r',
                    'findmnt /', 'systemctl is-system-running',
                    'systemctl --failed --no-pager',
                    'systemctl show -p Id -p ActiveState -p SubState -p UnitFileState '
                    'sshd.service NetworkManager.service systemd-logind.service',
                    'ip -brief addr',
                    "printf '\\nPJA110_QEMU_END\\n'", 'systemctl poweroff',
                ]
                channel.sendall(('; '.join(commands) + '\n').encode())
                receive_until(b'\nPJA110_QEMU_END\r\n', 300)
                observed = transcript.decode(errors='replace').replace('\r', '')
                try:
                    proc.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    proc.wait(timeout=10)
                console = (out / 'console.log').read_text(errors='replace')
                states = {}
                for block in observed.split('\n\n'):
                    fields = dict(re.findall(r'^(Id|ActiveState|SubState|UnitFileState)=(.*)$',
                                             block, re.M))
                    if 'Id' in fields:
                        states[fields.pop('Id')] = fields
                result = {
                    'payload': payload,
                    'kernel_release_seen': next((l for l in observed.splitlines()
                                                 if l.startswith('6.')), None),
                    'pid1': 'systemd' if '\nsystemd\n' in observed else None,
                    'diagnostics_complete': '\nPJA110_QEMU_END\n' in observed,
                    'clean_poweroff': 'reboot: Power down' in console,
                    'qemu_exit': proc.returncode,
                    'services': states,
                    'root_uuid_used': info['root_uuid'],
                    'checks': {
                        'boots_to_systemd': '\nsystemd\n' in observed,
                        'services_active': all(states.get(s, {}).get('ActiveState') == 'active'
                                               for s in ('sshd.service',
                                                         'NetworkManager.service',
                                                         'systemd-logind.service')),
                        'clean_poweroff': 'reboot: Power down' in console,
                    },
                    'limitations': ['does not cover DSI, touch, ADC, charging, Wi-Fi '
                                    'hardware or UFS slot management',
                                    'does not write any phone partition'],
                }
                (out / 'result.json').write_bytes(
                    (json.dumps(result, indent=2, ensure_ascii=False) + '\n').encode())
                print(json.dumps(result['checks'], indent=2))
                print(json.dumps({'kernel': result['kernel_release_seen'],
                                  'pid1': result['pid1'],
                                  'clean_poweroff': result['clean_poweroff'],
                                  'qemu_exit': result['qemu_exit'],
                                  'services': states}, indent=2))
                assert result['checks']['boots_to_systemd'], 'systemd did not start'
                assert result['checks']['services_active'], 'core services not active'
                assert result['checks']['clean_poweroff'], 'no clean poweroff'
                print('PASS: generated slot-A payload boots to systemd and powers off cleanly')
            finally:
                channel.close()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


if __name__ == '__main__':
    main()
