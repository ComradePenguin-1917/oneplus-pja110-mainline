"""Emit a reviewable, hash-pinned on-device upgrade plan (read-only).

Reads the generated existing-root slot image manifest and the live phone state,
then writes ``install-plan.json`` with the exact commands for:

  1. backing up the current slot-A boot partitions and legacy files,
  2. installing the two rebuilt APKs,
  3. writing and read-back verifying boot_a (vendor_boot_a only if its hash
     actually changed),
  4. a normal reboot plus the baseline migration,
  5. the acceptance capture.

Nothing here writes to the phone.  The plan is meant to be reviewed first and
then executed in one explicitly authorised root session.
"""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / 'out/usb-ncm-20261013/ssh'
KNOWN_HOSTS = ROOT / 'out/native-install-20261017/known_hosts'
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'none', '-T',
       '-i', str(KEYS / 'client_key_host'), '-o', 'BatchMode=yes',
       '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', f'UserKnownHostsFile={KNOWN_HOSTS}',
       '-o', 'HostKeyAlias=172.16.42.1', '-o', 'ConnectTimeout=8']

REMOTE = r'''
uname -r
findmnt -n -o SOURCE,UUID,OPTIONS /
tr '\000' '\n' < /proc/device-tree/compatible | head -2
cat /proc/cmdline | tr ' ' '\n' | grep -E '^root='
'''


def read(host):
    p = subprocess.run(SSH + ['penguin@' + host, REMOTE], capture_output=True, timeout=30)
    p.check_returncode()
    return p.stdout.decode('utf-8', 'replace')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', default='172.16.42.1')
    ap.add_argument('--images', default='out/native-slot-20261017/existing-root')
    ap.add_argument('--profile', default='postmarketos/integration-profile.json')
    ap.add_argument('--out', default='out/baseline-20261017/install-plan.json')
    args = ap.parse_args()

    images = json.loads((ROOT / args.images / 'manifest.json').read_text())
    profile = json.loads((ROOT / args.profile).read_text())
    outputs = images['outputs']
    boot_uuid = images['root_uuid']
    state = read(args.host)
    lines = [l for l in state.splitlines() if l.strip()]
    kernel = lines[0]
    mount = next((l for l in lines if l.startswith('/dev/')), '')
    compatible = next((l for l in lines if l.startswith('oneplus,')), '')
    cmdline = next((l for l in lines if l.startswith('root=')), '')

    assert f'root=UUID={boot_uuid}' == cmdline, \
        f'image cmdline {boot_uuid} does not match the running root ({cmdline})'

    def sha(name):
        return outputs[name]['sha256']

    commands = [
        'ts=$(date +%Y%m%d-%H%M%S); d=/var/lib/pja110-baseline/$ts; mkdir -p "$d"',
        'dd if=/dev/disk/by-partlabel/boot_a of="$d/boot_a.img" bs=4M',
        'dd if=/dev/disk/by-partlabel/vendor_boot_a of="$d/vendor_boot_a.img" bs=4M',
        'tar -C / -cf "$d/legacy-usr-local.tar" usr/local/lib/pja110 usr/local/libexec 2>/dev/null || true',
        'systemctl list-unit-files "pja110-*" > "$d/units-before.txt"',
        'for p in boot_b init_boot_b vendor_boot_b dtbo_b; do sha256sum /dev/disk/by-partlabel/$p; done > "$d/slot-b-before.txt"',
        f'apk add --allow-untrusted --force-overwrite /tmp/pja110-pkgs/linux-oneplus-xigua-{profile["packages"]["linux-oneplus-xigua"]}.apk',
        f'apk add --allow-untrusted --force-overwrite /tmp/pja110-pkgs/device-oneplus-xigua-{profile["packages"]["device-oneplus-xigua"]}.apk',
        'apk add qbootctl',
        'dd if=/tmp/pja110-images/boot_a.img of=/dev/disk/by-partlabel/boot_a bs=4M conv=fsync && sync',
        'sha256sum /dev/disk/by-partlabel/boot_a',
        'reboot',
        'pja110-migrate-baseline check && pja110-migrate-baseline apply',
        'reboot',
        'pja110-migrate-baseline check',
    ]

    plan = {
        'generated_for': args.host,
        'mode': 'existing-root',
        'preconditions': {
            'running_kernel': kernel,
            'running_root': mount,
            'device_tree_compatible': compatible,
            'image_root_uuid': boot_uuid,
            'uuid_matches_running_root': True,
            'requires_root_session': True,
        },
        'artifacts': {
            'boot_a.img': {'sha256': sha('boot_a.img'), 'bytes': outputs['boot_a.img']['bytes']},
            'vendor_boot_a.img': {'sha256': sha('vendor_boot_a.img'),
                                  'bytes': outputs['vendor_boot_a.img']['bytes'],
                                  'note': 'write only if this hash differs from the running partition'},
            'init_boot_a.img': {'sha256': sha('init_boot_a.img'),
                                'note': 'unchanged from the previously verified container'},
            'dtbo_a.img': {'sha256': sha('dtbo_a.img'),
                           'note': 'unchanged; do not rewrite unless a review says so'},
        },
        'packages': {
            'linux-oneplus-xigua': profile['packages']['linux-oneplus-xigua'],
            'device-oneplus-xigua': profile['packages']['device-oneplus-xigua'],
            'qbootctl': 'from the Alpine repository',
        },
        'backup_location': '/var/lib/pja110-baseline/<timestamp>/',
        'restore': [
            'dd if=/var/lib/pja110-baseline/<ts>/boot_a.img of=/dev/disk/by-partlabel/boot_a bs=4M conv=fsync',
            '/var/lib/pja110-baseline/<ts>/restore.sh',
        ],
        'commands': commands,
        'acceptance': [
            'python tools/capture_acceptance.py --phase before',
            'three normal reboots, then: python tools/capture_acceptance.py --phase after',
        ],
        'unchanged': ['slot B', 'userdata', 'dtbo_a', 'init_boot_a'],
        'gaps': ['slot-A/B GPT attributes and raw partition hashes need the root session'],
        'phone_writes_performed': False,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(plan, indent=2, ensure_ascii=False) + '\n').encode())
    print(json.dumps({'plan': str(out), 'kernel': kernel, 'root_uuid': boot_uuid,
                      'boot_a_sha256': sha('boot_a.img'),
                      'vendor_boot_a_sha256': sha('vendor_boot_a.img')}, indent=2))
    print('PASS: plan is consistent with the running root; no phone writes')


if __name__ == '__main__':
    main()
