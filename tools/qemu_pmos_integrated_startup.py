"""Observe automatic service startup on an unmodified, snapshot-backed pmOS image.

Run with WSL python3. The root debug shell is VM-only, on a separate virtio
console; it never starts the services being tested. No phone access or sudo.
"""
from pathlib import Path
import json
import hashlib
import re
import socket
import subprocess
import tempfile
import time
import sys
from pmos_image_info import inspect_image

base = Path('/mnt/h/workspace/PJA110-Mainline')
export = Path('/tmp/postmarketOS-export')
out = base / 'out/postmarketos-integration-20261016/qemu-startup'
userdata_mode = '--userdata-rootfs' in sys.argv[1:]
native_mode = '--native-images' in sys.argv[1:] or userdata_mode
root_disk = export / 'oneplus-xigua.img'
kernel = export / 'vmlinuz'
initrd = export / 'initramfs'
if native_mode:
    native = base / 'out/native-install-20261016/native-images'
    manifest = json.loads((native/'manifest.json').read_text())
    for name in ['extracted-kernel', 'combined-initrd.lz4']:
        assert hashlib.sha256((native/name).read_bytes()).hexdigest()==manifest['files'][name]['sha256']
    kernel = native/'extracted-kernel'
    initrd = native/'combined-initrd.lz4'
    out = native/'qemu-startup'
if userdata_mode:
    root_output = base/'out/native-install-20261016/rootfs'
    root_manifest = json.loads((root_output/'manifest.json').read_text())
    root_disk = Path(root_manifest['qemu_disk'])
    assert root_disk.stat().st_size==root_manifest['userdata_bytes']
    with root_disk.open('rb') as f:
        h=hashlib.sha256()
        remaining=root_manifest['prefix_bytes']
        while remaining:
            block=f.read(min(4*1024*1024,remaining)); assert block
            h.update(block); remaining-=len(block)
        assert h.hexdigest()==root_manifest['prefix_sha256']
        f.seek(root_manifest['tail_offset'])
        assert hashlib.sha256(f.read()).hexdigest()==root_manifest['tail_sha256']
    out=root_output/'qemu-startup'
out.mkdir(parents=True, exist_ok=True)
(out / 'result.json').unlink(missing_ok=True)
info = inspect_image(root_disk)
(out / 'image-info.json').write_text(json.dumps(info, indent=2) + '\n')
cmdline = (f'console=ttyAMA0 earlycon=pl011,0x9000000 loglevel=4 '
           f'root=UUID={info["root_uuid"]} rw systemd.log_target=console '
           'systemd.debug_shell=hvc0 systemd.mask=serial-getty@hvc0.service')
with tempfile.TemporaryDirectory(prefix='pmos-qemu-') as scratch:
    address = str(Path(scratch) / 'debug.sock')
    args = ['qemu-system-aarch64', '-machine', 'virt', '-accel', 'tcg',
            '-cpu', 'max', '-smp', '2', '-m', '2048', '-display', 'none',
            '-serial', 'file:' + str(out / 'console.log'), '-monitor', 'none',
            '-no-reboot', '-kernel', str(kernel),
            '-initrd', str(initrd), '-append', cmdline,
            '-drive', f'if=none,id=pmos,file={root_disk},format=raw,snapshot=on',
            '-device', 'virtio-blk-pci,drive=pmos,logical_block_size=4096,physical_block_size=4096',
            '-netdev', 'user,id=net0,hostfwd=tcp:127.0.0.1:2225-:22',
            '-device', 'virtio-net-pci,netdev=net0',
            '-device', 'virtio-serial-pci', '-chardev',
            f'socket,id=debug,path={address},server=on,wait=off',
            '-device', 'virtconsole,chardev=debug']
    (out / 'command.json').write_text(json.dumps(args, indent=2) + '\n')
    with (out / 'qemu-stderr.log').open('wb') as err:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=err, stderr=err)
        channel = socket.socket(socket.AF_UNIX)
        channel.settimeout(1)
        transcript = bytearray()
        try:
            for _ in range(30):
                if Path(address).exists():
                    break
                if proc.poll() is not None:
                    raise RuntimeError('QEMU failed to launch; inspect qemu-stderr.log')
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

            assert receive_until(b'# ', 180), 'VM diagnostic console unavailable'
            # A single parsed command prevents later input being flushed by tty setup.
            commands = [
                'stty -echo', 'export SYSTEMD_COLORS=0 SYSTEMD_PAGER=cat',
                "printf '\\nPMOS_DIAGNOSTIC_QUEUED\\n'", 'sleep 110',
                "printf '\\nPMOS_AUTOSTART_BEGIN\\n'", 'cat /proc/1/comm', 'uname -r',
                'findmnt /', 'findmnt /boot', 'systemctl get-default',
                'systemctl is-system-running', 'systemctl list-jobs --no-pager',
                'systemctl --failed --no-pager',
                'systemctl show -p Id -p ActiveState -p SubState -p Result -p UnitFileState '
                'systemd-firstboot.service sshd.service NetworkManager.service '
                'systemd-logind.service greetd.service nftables.service postmarketos-zram-swap.service',
                'journalctl -b -u systemd-firstboot -u greetd -u sshd -u NetworkManager '
                '-u systemd-logind -u hkdm --no-pager -n 130',
                'ip -brief addr', 'ss -lnt', 'swapon --show',
                "printf '\\nPMOS_AUTOSTART_END\\n'", 'systemctl poweroff',
            ]
            channel.sendall(('; '.join(commands) + '\n').encode())
            complete = receive_until(b'\nPMOS_AUTOSTART_END\r\n', 240)
            observed = transcript.decode(errors='replace').replace('\r', '')
            complete = '\nPMOS_AUTOSTART_END\n' in observed
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)
            console = (out / 'console.log').read_text(errors='replace')
            result = {'diagnostics_complete': complete, 'qemu_exit': proc.returncode,
                      'clean_poweroff': 'reboot: Power down' in console,
                      'services_started_manually': False,
                      'firstboot_masked': False, 'graphical_target_overridden': False,
                      'debug_shell': 'VM-only hvc0', 'source_disk_write_mode': 'snapshot'}
            if native_mode:
                result['native_packaged_combined_initrd'] = True
                result['kernel_sha256'] = manifest['files']['extracted-kernel']['sha256']
                result['combined_initrd_sha256'] = manifest['files']['combined-initrd.lz4']['sha256']
                result['phone_abl_split_image_loading_tested'] = False
            states = {}
            for block in observed.split('\n\n'):
                fields = dict(re.findall(r'^(Id|ActiveState|SubState|Result|UnitFileState)=(.*)$', block, re.M))
                if 'Id' in fields:
                    states[fields.pop('Id')] = fields
            result['services'] = states
            (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
            print(transcript.decode(errors='replace')[-18000:])
            assert complete, 'Automatic startup diagnostics not completed'
            assert result['clean_poweroff'] and proc.returncode == 0, 'Clean guest poweroff not observed'
            if native_mode:
                assert '6.14.0-oneplus-xigua' in observed
                assert '\nsystemd\n' in observed
                for service in ['sshd.service', 'NetworkManager.service', 'systemd-logind.service']:
                    assert states[service]['ActiveState']=='active', service
                if userdata_mode:
                    root_manifest['qemu_full_geometry_boot_passed']=True
                    root_manifest['qemu_clean_poweroff_passed']=True
                    (root_output/'manifest.json').write_text(json.dumps(root_manifest,indent=2)+'\n')
                else:
                    manifest['qemu_combined_payload_tested'] = True
                    manifest['qemu_result'] = 'qemu-startup/result.json'
                    (native/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        finally:
            channel.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
