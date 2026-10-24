"""Capture the stage-6 acceptance evidence (read-only, no root required).

Produces a per-item record with ``passed`` / ``failed`` / ``pending`` and the
evidence source for each item.  The overall result is ``failed`` if anything
failed, ``incomplete`` if anything still needs root-only data or visual
confirmation, and only then ``passed``.  Pending items are never silently folded
into a pass.
"""
import argparse
import json
import re
import subprocess
import time
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
set +e
echo "@@identity"
date -Is; uname -r; cat /proc/sys/kernel/random/boot_id; cat /proc/1/comm
tr '\000' '\n' < /proc/device-tree/compatible | head -3
findmnt -n -o OPTIONS /
echo "@@packages"
apk --no-network info -v 2>/dev/null | grep -E '^(linux-oneplus-xigua|device-oneplus-xigua|qbootctl)-'
echo "@@modules"
for m in qcom_battmgr qcom_spmi_adc5_gen3 qcom_vadc_common ath12k synaptics_aston; do
  if [ -d "/sys/module/$m" ]; then
    echo "MOD $m loaded version=$(cat /sys/module/$m/version 2>/dev/null)"
  else
    echo "MOD $m missing"
  fi
  echo "FILE $m $(modinfo -F filename "$m" 2>/dev/null)"
done
echo "@@power"
for d in /sys/class/power_supply/*; do
  echo "PSU ${d##*/} type=$(cat "$d/type" 2>/dev/null) status=$(cat "$d/status" 2>/dev/null) cap=$(cat "$d/capacity" 2>/dev/null) online=$(cat "$d/online" 2>/dev/null) current=$(cat "$d/current_now" 2>/dev/null)"
done
echo "@@adc"
for d in /sys/bus/iio/devices/iio:device*; do
  [ -d "$d" ] || continue
  echo "IIO ${d##*/} name=$(cat "$d/name" 2>/dev/null)"
  for f in "$d"/in_temp*_input; do [ -f "$f" ] && echo "TEMP ${f##*/}=$(cat "$f")"; done
done
echo "@@display"
cat /sys/class/drm/card0-DSI-1/status 2>/dev/null
cat /sys/class/drm/card0-DSI-1/modes 2>/dev/null
pgrep -a phoc; pgrep -a phosh
for e in /dev/input/event*; do
  n=$(cat "/sys/class/input/${e##*/}/device/name" 2>/dev/null)
  echo "INPUT ${e##*/} name=${n}"
done
echo "@@network"
ip -brief address
nmcli -t -f DEVICE,TYPE,STATE device
echo "@@services"
systemctl list-unit-files --no-pager 'pja110-*'
systemctl --failed --no-pager
echo "@@boots"
journalctl --list-boots --no-pager 2>/dev/null
echo "@@legacy"
ls -d /usr/local/lib/pja110 2>/dev/null
ls /usr/local/libexec/pja110* 2>/dev/null
ls /etc/systemd/system/pja110-*.service 2>/dev/null
echo "@@rootonly"
sha256sum /dev/disk/by-partlabel/boot_a 2>&1 | head -1
/usr/bin/qbootctl -a 2>&1 | head -3
echo "@@end"
'''


def run(host, command, timeout=90):
    p = subprocess.run(SSH + ['penguin@' + host, command], capture_output=True, timeout=timeout)
    return p.returncode, p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace')


def sections(text):
    out, current = {}, None
    for line in text.splitlines():
        if line == '@@end':
            current = None
        elif line.startswith('@@'):
            current = line[2:].strip()
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def ssh_ok(host):
    p = subprocess.run(SSH + ['penguin@' + host, 'true'], capture_output=True, timeout=20)
    return p.returncode == 0


def item(items, ident, status, evidence, note):
    assert status in ('passed', 'failed', 'pending'), status
    items.append({'id': ident, 'status': status, 'evidence': evidence, 'note': note})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', default='172.16.42.1')
    ap.add_argument('--phase', choices=['before', 'after'], required=True)
    ap.add_argument('--out-dir', default='out/baseline-20261017')
    ap.add_argument('--profile', default='postmarketos/integration-profile.json')
    ap.add_argument('--root-evidence', default='out/baseline-20261017/phone-logs',
                    help='directory holding phase3 logs for root-only slot facts')
    ap.add_argument('--confirm-display-touch', action='store_true',
                    help='operator confirms dynamic display and two-finger touch visually')
    ap.add_argument('--pre-upgrade-boot', default='8abcc6d7-443a-41c9-83c6-eaf139a48887',
                    help='last boot id before the upgrade (without one, journal order)')
    ap.add_argument('--slot-manifest', default='out/native-slot-20261017/existing-root/manifest.json',
                    help='slot image manifest used to check the phase3 read-back hashes')
    args = ap.parse_args()

    code, text, err = run(args.host, REMOTE)
    if code != 0 and not text:
        raise SystemExit(f'ssh failed: {err}')
    sec = sections(text)
    profile = json.loads((ROOT / args.profile).read_text()) if (ROOT / args.profile).is_file() else None
    out = ROOT / args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    mods, psus, boots = {}, {}, []
    for line in sec.get('modules', []):
        if line.startswith('MOD '):
            _, name, state, *rest = line.split()
            mods.setdefault(name, {})['state'] = state
            for blob in rest:
                if '=' in blob:
                    k, v = blob.split('=', 1)
                    mods[name][k] = v
        elif line.startswith('FILE '):
            _, name, path = line.split(' ', 2)
            mods.setdefault(name, {})['path'] = path
    for line in sec.get('power', []):
        if line.startswith('PSU '):
            bits = line.split()
            psus[bits[1]] = dict(x.split('=', 1) for x in bits[2:] if '=' in x)
    for line in sec.get('boots', []):
        parts = line.split()
        # journalctl --list-boots: "  0 <id> <first> <last>" (short format)
        if len(parts) >= 2 and len(parts[1]) == 32 and all(c in '0123456789abcdef' for c in parts[1]):
            boots.append(parts[1])

    identity = sec.get('identity', [])
    boot_id = identity[2] if len(identity) > 2 else None
    kernel = identity[1] if len(identity) > 1 else None
    pid1 = identity[3] if len(identity) > 3 else None
    compatible = [l for l in identity if l.startswith(('oneplus,', 'qcom,'))]
    iio = next((l.split('name=', 1)[1] for l in sec.get('adc', []) if 'name=' in l), None)
    temps = [l for l in sec.get('adc', []) if l.startswith('TEMP ')]
    display = sec.get('display', [])
    dsi = next((l for l in display if l in ('connected', 'disconnected')), None)
    modes = next((l for l in display if l.startswith('1240x')), None)
    phoc = [l for l in display if 'phoc' in l]
    inputs = [l for l in display if l.startswith('INPUT ')]
    network = sec.get('network', [])
    wlan = next((l for l in network if l.startswith('wlan0 ')), '')
    service_lines = sec.get('services', [])
    legacy = [l for l in sec.get('legacy', []) if l.strip()]
    packages = sec.get('packages', [])
    gaps = [l for l in sec.get('rootonly', []) if 'Permission denied' in l or 'denied' in l]

    items = []
    ok = lambda cond: 'passed' if cond else 'failed'

    item(items, 'pid1_systemd', ok(pid1 == 'systemd'), 'remote /proc/1/comm', pid1 or 'unknown')
    item(items, 'device_tree_identity', ok(any('oneplus,xigua' == c for c in compatible)),
         'remote /proc/device-tree/compatible', ','.join(compatible))
    item(items, 'kernel_release', ok(kernel == '6.14.0-oneplus-xigua'), 'remote uname -r', kernel or '?')
    if profile and args.phase == 'after':
        want = profile['packages']
        have = {pkg: next((l[len(pkg) + 1:] for l in packages
                           if l.startswith(pkg + '-')), None) for pkg in want}
        checks = {
            'linux-oneplus-xigua': want['linux-oneplus-xigua'],
            'device-oneplus-xigua': want['device-oneplus-xigua'],
        }
        got = {k: have.get(k) for k in checks}
        item(items, 'package_versions', ok(all(checks[k] == got[k] for k in checks)),
             'remote apk info -v vs integration-profile.json', json.dumps(got))
    item(items, 'modules_loaded',
         ok(all(mods.get(m, {}).get('state') == 'loaded'
                for m in ('qcom_battmgr', 'qcom_spmi_adc5_gen3', 'qcom_vadc_common',
                          'ath12k', 'synaptics_aston'))),
         'remote /sys/module', json.dumps({m: mods.get(m, {}).get('state') for m in mods}))
    item(items, 'battmgr_version', ok(mods.get('qcom_battmgr', {}).get('version') ==
                                      'pja110-single-battery-1'),
         'remote /sys/module/qcom_battmgr/version',
         mods.get('qcom_battmgr', {}).get('version'))
    item(items, 'module_paths_packaged',
         ok(all((mods.get(m, {}).get('path') or '').startswith('/lib/modules/')
                for m in ('qcom_battmgr', 'qcom_spmi_adc5_gen3'))),
         'remote modinfo -F filename',
         json.dumps({m: mods.get(m, {}).get('path') for m in ('qcom_battmgr', 'qcom_spmi_adc5_gen3')}))
    item(items, 'single_battery_topology',
         ok('qcom-battmgr-bat' not in psus and 'bq28z610-0' in psus and 'qcom-battmgr-usb' in psus),
         'remote /sys/class/power_supply', ','.join(sorted(psus)))
    item(items, 'adc_temperature', ok(iio == 'spmi-adc5-gen3' and bool(temps)),
         'remote IIO sysfs', f'{iio}; {temps[:2]}')
    item(items, 'wifi_connected', ok('wlan0:wifi:connected' in network),
         'remote nmcli/ip', wlan.strip() or 'wlan0 missing')
    item(items, 'phoc_running', ok(bool(phoc)), 'remote pgrep -a phoc', '; '.join(phoc) or 'not running')
    item(items, 'dsi_output', ok(dsi == 'connected' and modes is not None),
         'remote /sys/class/drm', f'{dsi} {modes}')
    touch = [l for l in inputs if 's3910' in l.lower() or 'synaptics' in l.lower()]
    item(items, 'touch_device', ok(bool(touch)), 'remote /dev/input names', '; '.join(touch) or 'no match')
    item(items, 'legacy_absent', ok(not legacy), 'remote /usr/local and /etc scan',
         '; '.join(legacy) or 'none')

    wlan_ip = wlan.split()[2].split('/')[0] if len(wlan.split()) > 2 else None
    if args.phase == 'before':
        item(items, 'wireless_ssh', 'pending', 'not attempted before the upgrade', wlan_ip or 'no wlan0')
    else:
        item(items, 'wireless_ssh', ok(bool(wlan_ip) and ssh_ok(wlan_ip)),
             f'SSH over wlan0 {wlan_ip}', 'authenticated with the pinned host key alias')

    # Boot count relative to the last "before" capture, or to the last known
    # pre-upgrade boot id when no structured "before" record exists.
    before_files = sorted((out).glob('acceptance-before-*.json'))
    new_boots = None
    before_boots = []
    if before_files:
        try:
            prev = json.loads(before_files[-1].read_text())
            before_boots = prev.get('boots', [])
        except Exception:
            before_boots = []
    if boots:
        if before_boots:
            new_boots = [b for b in boots if b not in before_boots]
        else:
            want_boot = args.pre_upgrade_boot.replace('-', '')
            if want_boot in boots:
                new_boots = boots[boots.index(want_boot) + 1:]
    if args.phase == 'after':
        if new_boots is not None:
            item(items, 'three_normal_boots', ok(len(new_boots) >= 3),
                 'journalctl --list-boots vs the pre-upgrade boot',
                 f'{len(new_boots)} new boots: {", ".join(new_boots)}')
        else:
            item(items, 'three_normal_boots', 'pending', 'boot list unavailable', '')

    if args.phase == 'after':
        ev = ROOT / args.root_evidence
        slot_logs = sorted(ev.glob('phase3-*.log')) if ev.is_dir() else []
        root_log = slot_logs[-1] if slot_logs else None
        log_text = root_log.read_text(errors='replace') if root_log else ''
        manifest = json.loads((ROOT / args.slot_manifest).read_text()) \
            if (ROOT / args.slot_manifest).is_file() else None
        boot_line = re.search(r'^boot_a=([0-9a-f]{64})$', log_text, re.M)
        vendor_line = re.search(r'^vendor_boot_a=([0-9a-f]{64})$', log_text, re.M)
        if not root_log or manifest is None:
            item(items, 'slot_a_images', 'pending',
                 f'root-only: {root_log or "no phase3 log"}',
                 'boot_a/vendor_boot_a read-back needs root')
        else:
            want = manifest['outputs']
            checks = {
                'boot_a': (boot_line.group(1) if boot_line else None,
                           want['boot_a.img']['sha256']),
                'vendor_boot_a': (vendor_line.group(1) if vendor_line else None,
                                  want['vendor_boot_a.img']['sha256']),
            }
            good = all(a == b for a, b in checks.values())
            item(items, 'slot_a_images', 'passed' if good else 'failed',
                 str(root_log), json.dumps({k: {'log': a, 'image': b}
                                            for k, (a, b) in checks.items()}))
        b_pairs = re.findall(r'^(boot_b|init_boot_b|vendor_boot_b|dtbo_b) now=([0-9a-f]{64}) was=([0-9a-f]{64})$',
                             log_text, re.M)
        if not root_log or not b_pairs:
            item(items, 'slot_b_unchanged', 'pending',
                 f'root-only: {root_log or "no phase3 log"}',
                 'partition hashes need root; compared in phase3 with the install transaction')
        else:
            good = len(b_pairs) == 4 and all(a == b for _, a, b in b_pairs) and 'FAIL' not in log_text
            item(items, 'slot_b_unchanged', 'passed' if good else 'failed',
                 str(root_log), json.dumps({p: {'now': a, 'before': b} for p, a, b in b_pairs}))
        item(items, 'display_and_touch_visual',
             'passed' if args.confirm_display_touch else 'pending',
             'operator visual confirmation' if args.confirm_display_touch else 'not confirmed',
             'dynamic rendering and two-finger touch')
        failed_units = [l for l in service_lines if l.strip().startswith('●')]
        item(items, 'failed_units', ok(not failed_units), 'remote systemctl --failed',
             '; '.join(failed_units) or 'none')

    statuses = {i['status'] for i in items}
    if args.phase == 'before':
        overall = 'baseline-record'
    else:
        overall = 'failed' if 'failed' in statuses else ('incomplete' if 'pending' in statuses else 'passed')

    record = {
        'phase': args.phase,
        'captured_at': identity[0] if identity else None,
        'host': args.host,
        'boot_id': boot_id,
        'boots': boots,
        'identity': identity,
        'packages': packages,
        'modules': mods,
        'power_supplies': psus,
        'adc': sec.get('adc', []),
        'display_input': display,
        'network': network,
        'services': service_lines,
        'legacy': legacy,
        'root_only_gaps': gaps,
        'items': items,
        'overall': overall,
        'pending_reasons': [i['id'] for i in items if i['status'] == 'pending'],
        'failed_items': [i['id'] for i in items if i['status'] == 'failed'],
    }
    stamp = time.strftime('%Y%m%d-%H%M%S')
    path = out / f'acceptance-{args.phase}-{stamp}.json'
    path.write_bytes((json.dumps(record, indent=2, ensure_ascii=False) + '\n').encode())
    latest = out / f'acceptance-{args.phase}-latest.json'
    latest.write_bytes(path.read_bytes())
    for i in items:
        print(f"{i['status']:7s} {i['id']:24s} {i['note'][:90]}")
    print(json.dumps({'phase': args.phase, 'overall': overall,
                      'pending': record['pending_reasons'],
                      'failed': record['failed_items'],
                      'record': str(path)}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
