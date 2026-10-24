"""Write only reviewed slot-A DTBO from B rescue; never reboot."""
from pathlib import Path
import hashlib, json, subprocess
from prepare_native_install import SSH
OUT = Path(__file__).resolve().parents[1] / 'out/native-install-20261017/dtbo-mainline-identity'
def run(cmd, data=None):
    p = subprocess.run(SSH + [cmd], input=data, capture_output=True, timeout=90)
    with (OUT / 'deployment.log').open('ab') as f:
        f.write((cmd + '\n').encode() + p.stdout + p.stderr)
    p.check_returncode()
    return p.stdout
def deploy():
    m = json.loads((OUT / 'manifest.json').read_text())
    image = (OUT / 'dtbo_a.img').read_bytes()
    sha = lambda b: hashlib.sha256(b).hexdigest()
    assert sha(image) == m['candidate_sha256']
    assert not (OUT / 'write-started.json').exists(), 'Inspect previous write before retry'
    state = run('uname -a; cat /proc/sys/kernel/random/boot_id')
    assert b'#24 SMP' in state
    listing = run('for p in /sys/class/block/sd*; do cat "$p/uevent"; echo END_BLOCK; done').decode()
    parts = {}
    for record in listing.split('END_BLOCK'):
        fields = dict(line.split('=', 1) for line in record.splitlines() if '=' in line)
        if fields.get('PARTNAME') in ('dtbo_a', 'dtbo_b'):
            dev = fields['DEVNAME']
            assert dev.startswith('sd') and dev.isalnum()
            parts[fields['PARTNAME']] = '/dev/' + dev
    assert len(parts) == 2
    before = run('cat ' + parts['dtbo_a'])
    assert sha(before) == m['source_sha256'], 'A DTBO differs from reviewed source'
    assert len(before) == len(image)
    (OUT / 'dtbo_a-before.img').write_bytes(before)
    rescue = run('sha256sum ' + parts['dtbo_b']).decode().split()[0]
    remote = '/tmp/dtbo-mainline-identity.img'
    assert run('cat > ' + remote + ' && sha256sum ' + remote, image).decode().split()[0] == m['candidate_sha256']
    (OUT / 'write-started.json').write_text(json.dumps({'state': state.decode(), 'before_sha256': sha(before)}))
    run('dd if=' + remote + ' of=' + parts['dtbo_a'] + ' bs=1048576 conv=fsync && sync')
    actual = run('sha256sum ' + parts['dtbo_a']).decode().split()[0]
    assert actual == m['candidate_sha256']
    assert run('sha256sum ' + parts['dtbo_b']).decode().split()[0] == rescue
    result = dict(a_dtbo_written=True, readback_sha256=actual, readback_verified=True, b_dtbo_unchanged=True, other_partitions_written=False, rebooted=False, runtime_verified=False)
    (OUT / 'deployment-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
if __name__ == '__main__':
    deploy()
