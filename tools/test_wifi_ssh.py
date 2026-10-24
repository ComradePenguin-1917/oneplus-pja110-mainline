"""Verify pinned wireless SSH identity and three binary round trips."""
import argparse
import hashlib
import ipaddress
import json
import secrets
import subprocess
import time
from pathlib import Path

from prepare_native_install import SSH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('address', type=ipaddress.IPv4Address)
    opts = parser.parse_args()
    args = [x if not x.startswith('UserKnownHostsFile=') else
            'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in SSH]
    args[-1:] = ['-o', 'HostKeyAlias=172.16.42.1', f'penguin@{opts.address}']
    out = Path('out/wifi-bringup-20261017')
    result = {'address': str(opts.address), 'round_trips': []}

    def remote(command, data=None):
        p = subprocess.run(args + [command], input=data, capture_output=True, timeout=60)
        if p.returncode:
            raise RuntimeError(p.stderr.decode(errors='replace'))
        return p.stdout

    result['inventory'] = remote('''echo SSH_CONNECTION=$SSH_CONNECTION
cat /proc/sys/kernel/random/boot_id
cat /sys/module/ath12k/version /sys/module/ath12k/srcversion
ip -brief address
ip route
nmcli -t -f NAME,TYPE,DEVICE connection show --active
rfkill list
''').decode()
    print(result['inventory'], flush=True)
    for i in range(3):
        payload = secrets.token_bytes(1024 * 1024)
        target = '/tmp/pja110-wifi-check-' + secrets.token_hex(8)
        start = time.monotonic()
        try:
            remote(f'umask 077; cat > {target}', payload)
            digest = remote(f'sha256sum {target}').decode().split()[0]
            returned = remote(f'cat {target}')
            expected = hashlib.sha256(payload).hexdigest()
            if digest != expected or returned != payload:
                raise RuntimeError('Wireless binary round trip mismatch')
            row = {'bytes': len(payload), 'sha256': expected,
                   'elapsed_seconds': round(time.monotonic() - start, 3), 'passed': True}
            result['round_trips'].append(row)
            print(f'Round trip {i + 1}: PASS ({len(payload)} bytes)', flush=True)
        finally:
            remote(f'rm -f {target}')
    result['kernel_wifi_log'] = remote(
        "journalctl -b -k --no-pager | grep -Ei 'ath12|mhi.*(error|fail)|firmware.*crash' | tail -n 65").decode()
    result['passed'] = True
    path = out / ('wireless-ssh-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('PASS: pinned wireless SSH and 3 x 1 MiB binary round trips;', path)


if __name__ == '__main__':
    main()
