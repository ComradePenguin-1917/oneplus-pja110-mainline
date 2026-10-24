"""Build a deterministic archive from the proven initramfs and SSH identity."""
import gzip
import hashlib
import json
import struct
import subprocess
from pathlib import Path
from build_init_marker_test import parse_cpio, make_entry

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/debug-ncm-fixed-20261013'
BASE = ROOT / 'out/user-init-usb-serial-diag-20261013'
SSH = ROOT / 'out/usb-ncm-20261013/ssh'

def main():
    OUT.mkdir(exist_ok=True)
    host = OUT / 'host-ed25519'
    if not host.exists():
        command = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'none', '-T',
                   '-i', str(SSH/'client_key_host'), '-o', 'BatchMode=yes',
                   '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', f'UserKnownHostsFile={SSH/"known_hosts"}',
                   '-o', 'ConnectTimeout=10', 'root@169.254.42.1',
                   'cat /tmp/ncm-host-ed25519']
        result = subprocess.run(command, capture_output=True, timeout=30, check=True)
        assert 40 < len(result.stdout) < 4096
        host.write_bytes(result.stdout)
    binary = (SSH/'dropbearmulti').read_bytes()
    assert binary[:4] == b'\x7fELF' and struct.unpack_from('<H', binary, 18)[0] == 183
    phoff = struct.unpack_from('<Q', binary, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', binary, 54)
    assert all(struct.unpack_from('<I', binary, phoff+i*phsize)[0] != 3 for i in range(phnum))
    public = (SSH/'client_key_host.pub').read_bytes()
    assert public.startswith(b'ssh-ed25519 ')
    init = (ROOT/'tools/debug_ncm_init.sh').read_bytes().replace(b'\r\n', b'\n')
    replacements = {'init': (0o100755, init)}
    additions = {
        'etc': (0o40755, b''),
        'etc/dropbear': (0o40700, b''),
        'etc/dropbear/host-ed25519': (0o100600, host.read_bytes()),
        'etc/passwd': (0o100644, b'root:x:0:0:root:/root:/bin/sh\n'),
        'etc/group': (0o100644, b'root:x:0:\n'),
        'root': (0o40700, b''), 'root/.ssh': (0o40700, b''),
        'root/.ssh/authorized_keys': (0o100600, public),
        'sbin/dropbearmulti': (0o100755, binary),
    }
    entries = parse_cpio(gzip.decompress((BASE/'initramfs.cpio.gz').read_bytes()))
    mapping = {n.removeprefix('./'): (f,d) for f,n,d in entries}
    assert 'bin/busybox' in mapping
    changes = replacements | additions
    ino = max(f[0] for f,n,d in entries)+1
    output = bytearray()
    for fields, name, data in entries:
        normalized = name.removeprefix('./')
        if name == 'TRAILER!!!':
            for path, (mode, content) in additions.items():
                if path in mapping:
                    continue
                f = [ino,mode,0,0,1,0,0,0,0,0,0,0,0]
                output += make_entry(f,path,content)
                ino += 1
        if normalized in changes:
            mode,data = changes[normalized]
            fields = list(fields); fields[1] = mode
        output += make_entry(fields,name,data)
    rebuilt = {n.removeprefix('./'): (f,d) for f,n,d in parse_cpio(output)}
    for path,(mode,data) in changes.items():
        assert rebuilt[path][0][1] == mode and rebuilt[path][1] == data, path
        parent=Path(path).parent
        while str(parent)!='.':
            assert parent.as_posix() in rebuilt, f'missing parent: {parent}'
            assert rebuilt[parent.as_posix()][0][1]&0o170000==0o40000, f'parent not directory: {parent}'
            parent=parent.parent
    for path,(fields,data) in mapping.items():
        if path not in changes:
            assert rebuilt[path] == (fields,data), path
    archive = gzip.compress(output, compresslevel=9, mtime=0)
    (OUT/'initramfs.cpio.gz').write_bytes(archive)
    (OUT/'init.sh').write_bytes(init)
    (OUT/'archive-verification.json').write_text(json.dumps({
        'base': str(BASE.relative_to(ROOT)), 'entries': len(rebuilt),
        'archive_sha256': hashlib.sha256(archive).hexdigest(),
        'unchanged_entries_verified': True, 'static_arm64_dropbear_verified': True,
        'client_private_key_embedded': False, 'host_identity_preserved': True,
        'ssh_port':22,'phone_ip':'169.254.42.1',
    },indent=2)+'\n')
    print('PASS: fixed NCM/SSH initramfs assembled; existing host identity retained')

if __name__ == '__main__':
    main()
