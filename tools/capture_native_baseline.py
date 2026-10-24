"""Read-only baseline capture for the running native PJA110 system.

Collects, without changing the phone:

  * every ``pja110-*`` systemd unit, drop-in, enablement state and script,
  * modules-load / modprobe rules, module paths, parameters and load order,
  * file ownership (``apk info --who-owns``) and SHA256 for local artifacts,
  * the running device tree, compared with the packaged ``verified-vendor.dtb``,
  * root UUID, loop layout and partition inventory,
  * power / ADC / display / Wi-Fi runtime state.

Writes ``baseline-manifest.json`` plus ``diff-table.md`` into the output
directory.  Anything that needs root is recorded as an explicit gap instead of
being guessed from older evidence.
"""
import argparse
import hashlib
import io
import json
import os
import re
import struct
import subprocess
import sys
import tarfile
from pathlib import Path

from fdt import FDT

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / 'out/usb-ncm-20261013/ssh'
KNOWN_HOSTS = ROOT / 'out/native-install-20261017/known_hosts'
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'none', '-T',
       '-i', str(KEYS / 'client_key_host'), '-o', 'BatchMode=yes',
       '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', f'UserKnownHostsFile={KNOWN_HOSTS}',
       '-o', 'HostKeyAlias=172.16.42.1', '-o', 'ConnectTimeout=8',
       '-o', 'ServerAliveInterval=5']

REMOTE_SCRIPT = r'''
set +e
say() { echo "@@SECTION $1"; }
say identity
date -Is
uname -a
cat /proc/sys/kernel/random/boot_id
cat /proc/1/comm
cat /proc/cmdline | tr ' ' '\n'
say system
cat /etc/os-release
apk --version
pmbootstrap --version 2>/dev/null
say mount
cat /proc/mounts
findmnt -no SOURCE,UUID,FSTYPE,OPTIONS /
findmnt -no SOURCE,UUID,FSTYPE,OPTIONS /boot
df -Pk /
say loops
for d in /sys/block/loop*/loop/backing_file; do echo "$d=$(cat "$d" 2>/dev/null)"; done
for d in /sys/block/loop*/loop/sizelimit; do echo "$d=$(cat "$d" 2>/dev/null)"; done
say blocks
for f in /sys/class/block/*/uevent; do
  d=${f%/uevent}
  echo "BLOCK ${d##*/}"
  cat "$f"
  echo "SIZE=$(cat "$d/size" 2>/dev/null)"
done
say partitions
for p in boot_a init_boot_a vendor_boot_a dtbo_a boot_b init_boot_b vendor_boot_b dtbo_b vbmeta_a vbmeta_b userdata super; do
  l=/dev/disk/by-partlabel/$p
  if [ -e "$l" ]; then
    r=$(readlink -f "$l")
    echo "PART $p $r $(cat /sys/class/block/${r##*/}/size 2>/dev/null)"
  else
    echo "PART $p MISSING"
  fi
done
say units
systemctl list-unit-files --no-pager 'pja110-*'
for u in $(systemctl list-unit-files --no-pager --plain 'pja110-*' | awk '{print $1}'); do
  echo "@@UNIT $u"
  systemctl is-enabled "$u" 2>&1
  systemctl is-active "$u" 2>&1
  systemctl show "$u" -p FragmentPath -p DropInPaths -p UnitFileState -p WantedBy -p After -p Before -p ExecStart -p ConditionPathExists 2>&1
  echo "@@CAT $u"
  systemctl cat "$u" --no-pager 2>&1
done
say unitdirs
ls -la /etc/systemd/system/systemd-modules-load.service.d 2>/dev/null
for d in /etc/systemd/system/*.d /etc/systemd/system/*/*.d; do
  [ -d "$d" ] || continue
  echo "@@DROPIN $d"
  for f in "$d"/*; do [ -f "$f" ] && { echo "--- $f"; cat "$f"; }; done
done
say modules_load
for f in /etc/modules-load.d/*.conf; do [ -f "$f" ] && { echo "@@FILE $f"; cat "$f"; }; done
say modprobe
for f in /etc/modprobe.d/*.conf; do [ -f "$f" ] && { echo "@@FILE $f"; cat "$f"; }; done
say usrlocal
find /usr/local -type f 2>/dev/null | sort | while read -r f; do
  echo "LOCAL $f $(stat -c '%a %U %G %s' "$f") $(sha256sum "$f" | cut -d' ' -f1)"
done
say localexec
for f in /usr/local/libexec/*; do
  [ -f "$f" ] || continue
  case "$f" in
    *qbootctl) echo "@@SKIPBINARY $f"; continue;;
  esac
  echo "@@FILE $f"
  cat "$f"
done
say localko
for f in /usr/local/lib/pja110/*.ko; do
  [ -f "$f" ] || continue
  echo "@@KO $f"
  sha256sum "$f"
  modinfo "$f" 2>&1 | grep -E '^(filename|version|srcversion|vermagic|depends|name|parm):'
done
say packagelist
apk --no-network info -v 2>/dev/null | sort
say ownership
for f in /usr/local/lib/pja110/*.ko /usr/local/libexec/* /etc/systemd/system/pja110-* /etc/modules-load.d/* /etc/modprobe.d/*; do
  [ -e "$f" ] || continue
  echo "OWN $f :: $(apk info --who-owns "$f" 2>&1 | head -1)"
done
say modules
cat /proc/modules
for m in /sys/module/*; do
  n=${m##*/}
  [ -d "$m/parameters" ] || continue
  case "$n" in
    ath12k|qcom_battmgr|qcom_spmi_adc5_gen3|qcom_vadc_common|synaptics_aston|bq27xxx_battery|bq27xxx_battery_i2c|pwrseq_qcom_wcn)
      echo "@@MODPARAM $n"
      for p in "$m"/parameters/*; do [ -f "$p" ] && echo "  ${p##*/}=$(cat "$p" 2>/dev/null)"; done
      echo "  version=$(cat "$m/version" 2>/dev/null) srcversion=$(cat "$m/srcversion" 2>/dev/null)"
      ;;
  esac
done
say kernelmodules
krel=$(uname -r)
echo "KREL=$krel"
echo "KMOD_COUNT=$(find /lib/modules/$krel -name '*.ko*' | wc -l)"
find /lib/modules/$krel -name '*.ko*' | grep -E 'qcom|adc|batt|ath12k|synaptics|bq27|rfkill|pwrseq|iio' | sort | while read -r f; do
  echo "KMOD $f $(stat -c %s "$f") $(sha256sum "$f" | cut -d' ' -f1) :: $(apk info --who-owns "$f" 2>&1 | head -1)"
done
echo "@@MODULESDEP"
for f in /lib/modules/$krel/modules.dep /lib/modules/$krel/modules.load /lib/modules/$krel/modules.alias; do
  [ -f "$f" ] && echo "FILE $f $(sha256sum "$f" | cut -d' ' -f1)"
done
grep -E 'qcom_battmgr|adc5|vadc|ath12k|synaptics|bq27' /lib/modules/$krel/modules.dep 2>/dev/null
say blacklists
apt=$(apk info 2>/dev/null | grep -c .)
for f in /etc/modprobe.d/*.conf; do [ -f "$f" ] && grep -H '^blacklist' "$f"; done
say power
for d in /sys/class/power_supply/*; do echo "@@PSU $d"; cat "$d/uevent"; done
upower -d 2>&1
say adc
for d in /sys/bus/iio/devices/iio:device*; do
  [ -d "$d" ] || continue
  echo "@@IIO $d name=$(cat "$d/name" 2>/dev/null) driver=$(readlink -f "$d/driver" 2>/dev/null)"
  for f in "$d"/in_*; do [ -f "$f" ] && echo "  ${f##*/}=$(cat "$f" 2>/dev/null)"; done
done
say display
for f in /sys/class/drm/card*-DSI-*/status /sys/class/drm/card*-DSI-*/modes; do [ -f "$f" ] && { echo "FILE $f"; cat "$f"; }; done
cat /proc/bus/input/devices
say services
systemctl --failed --no-pager
journalctl -b -p warning --no-pager | tail -n 80
say userfiles
find /home/penguin -maxdepth 2 -type f 2>/dev/null | sort | head -120
say dt
tar -c -C /proc/device-tree . 2>/dev/null | base64 | tr -d '\n'
echo
echo "@@END"
'''

# Paths that legitimately require root to read on slot A.  They are reported as
# gaps; the tool never substitutes older evidence for a fresh reading.
ROOT_ONLY = [
    ('/sys/firmware/fdt', 'running FDT blob (raw)'),
    ('/dev/disk/by-partlabel/boot_a', 'slot A boot image bytes'),
    ('/dev/disk/by-partlabel/boot_b', 'slot B boot image bytes'),
    ('/dev/disk/by-partlabel/init_boot_a', 'slot A generic ramdisk'),
    ('/dev/disk/by-partlabel/vendor_boot_a', 'slot A vendor boot'),
    ('/dev/disk/by-partlabel/dtbo_a', 'slot A DTBO'),
    ('/dev/disk/by-partlabel/vendor_boot_b', 'slot B vendor boot'),
    ('/dev/disk/by-partlabel/dtbo_b', 'slot B DTBO'),
    ('/dev/disk/by-partlabel/init_boot_b', 'slot B generic ramdisk'),
    ('qbootctl', 'boot-control slot state and attributes'),
]


def run(host, cmd, timeout=180):
    args = SSH + ['penguin@' + host, cmd]
    p = subprocess.run(args, capture_output=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sections(text):
    out = {}
    current = None
    for line in text.splitlines():
        if line == '@@END':
            current = None
            continue
        if line.startswith('@@SECTION '):
            current = line[len('@@SECTION '):].strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return out


def parse_dt_tree(tar_bytes):
    """Rebuild {node_path: {prop: value}} from a /proc/device-tree tarball."""
    nodes = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:') as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        for m in members:
            rel = m.name
            if rel.startswith('./'):
                rel = rel[2:]
            if rel in ('.', ''):
                continue
            parts = rel.split('/')
            node = '/' + '/'.join(parts[:-1]) if len(parts) > 1 else '/'
            prop = parts[-1]
            value = tar.extractfile(m).read()
            # /proc/device-tree synthesises a "name" property per node; the FDT
            # reader never sees it, so drop it to keep the comparison honest.
            if prop == 'name':
                continue
            nodes.setdefault(node, {})[prop] = value
        # Directories without properties still exist as nodes.
        for m in tar.getmembers():
            if not m.isdir():
                continue
            rel = m.name
            if rel.startswith('./'):
                rel = rel[2:]
            nodes.setdefault('/' + rel if rel not in ('', '.') else '/', {})
    return nodes


def printable(value):
    if len(value) == 4:
        return str(struct.unpack('>I', value)[0])
    if all(32 <= c < 127 or c == 0 for c in value):
        text = value.rstrip(b'\0').decode('ascii', 'replace')
        return text.replace('\x00', '\\0')
    return value.hex()


def phandle_map(nodes):
    mapping = {}
    for path, props in nodes.items():
        for key in ('phandle', 'linux,phandle'):
            raw = props.get(key)
            if raw and len(raw) == 4:
                mapping[struct.unpack('>I', raw)[0]] = path
    return mapping


def normalize_props(props, handles):
    out = {}
    for name, value in props.items():
        if name in ('phandle', 'linux,phandle'):
            out[name] = f'<{handles.get(struct.unpack(">I", value)[0], "?")}>'
            continue
        if len(value) and len(value) % 4 == 0 and len(value) <= 256:
            words = struct.unpack('>%dI' % (len(value) // 4), value)
            if any(w in handles for w in words) and name not in ('reg', 'ranges'):
                out[name] = ' '.join(f'<{handles[w]}>' if w in handles else f'<0x{w:x}>'
                                     for w in words)
                continue
        out[name] = printable(value)
    return out


def dt_semantic_diff(running, reference):
    run_map = {p: normalize_props(v, phandle_map(running)) for p, v in running.items()}
    ref_map = {p: normalize_props(v, phandle_map(reference)) for p, v in reference.items()}
    only_run = sorted(set(run_map) - set(ref_map))
    only_ref = sorted(set(ref_map) - set(run_map))
    changed = {}
    for path in sorted(set(run_map) & set(ref_map)):
        a, b = run_map[path], ref_map[path]
        diffs = {}
        for key in sorted(set(a) | set(b)):
            if a.get(key) != b.get(key):
                diffs[key] = {'running': a.get(key), 'reference': b.get(key)}
        if diffs:
            changed[path] = diffs
    return {'nodes_only_running': only_run,
            'nodes_only_reference': only_ref,
            'property_changes': changed}


INTERESTING = re.compile(
    r'(batt|bq28|adc|vadc|wifi|wcn|ath|pcie|rfkill|panel|dsi|touch|synaptics|iris|'
    r'charger|pmic-glink|fuel-gauge|gpio-keys|compatible|model|machine|thermal)', re.I)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', default='172.16.42.1')
    ap.add_argument('--out', default='out/baseline-20261017')
    args = ap.parse_args()
    if args.host.startswith('-') or any(c.isspace() for c in args.host):
        ap.error('invalid host')

    out = ROOT / args.out
    (out / 'raw').mkdir(parents=True, exist_ok=True)

    code, stdout, stderr = run(args.host, REMOTE_SCRIPT, timeout=240)
    text = stdout.decode('utf-8', 'replace')
    (out / 'raw' / 'phone-inventory.txt').write_bytes(stdout + stderr)
    if code != 0:
        print(stderr.decode('utf-8', 'replace'))
        raise SystemExit(f'remote inventory failed: {code}')
    sec = sections(text)

    base = {
        'generated_at': None,
        'device': {'host': args.host, 'codename': 'oneplus-xigua'},
        'identity': {},
        'build': {},
        'storage': {},
        'units': {},
        'modules': {},
        'packages': {},
        'runtime': {},
        'device_tree': {},
        'gaps': [],
        'classification': [],
    }

    ident = sec.get('identity', [])
    base['generated_at'] = ident[0] if ident else None
    base['identity'] = {
        'uname': next((l for l in ident if l.startswith('Linux ')), None),
        'boot_id': ident[2] if len(ident) > 2 else None,
        'pid1': ident[3] if len(ident) > 3 else None,
        'cmdline': ident[4:],
    }
    sysinfo = sec.get('system', [])
    base['build']['os_release'] = [l for l in sysinfo if '=' in l]
    base['build']['apk_version'] = next((l for l in sysinfo if l.startswith('apk-tools')), None)

    mounts = sec.get('mount', [])
    base['storage']['mounts'] = mounts
    base['storage']['root_uuid'] = None
    for line in mounts:
        if line.startswith('/ '):
            base['storage']['root_uuid'] = line
    base['storage']['loops'] = [l for l in sec.get('loops', []) if '=' in l]
    blocks = []
    name = None
    for line in sec.get('blocks', []):
        if line.startswith('BLOCK '):
            name = line.split()[1]
            blocks.append({'name': name, 'uevent': {}})
        elif '=' in line and blocks:
            k, v = line.split('=', 1)
            blocks[-1]['uevent'][k] = v
        elif line.startswith('SIZE=') and blocks:
            blocks[-1]['uevent']['SIZE'] = line[5:]
    base['storage']['blocks'] = blocks
    base['storage']['partitions'] = []
    for line in sec.get('partitions', []):
        if line.startswith('PART '):
            bits = line.split()
            base['storage']['partitions'].append({
                'name': bits[1],
                'device': bits[2] if len(bits) > 2 else None,
                'sectors': int(bits[3]) if len(bits) > 3 and bits[3].isdigit() else None,
            })

    # ---- units -----------------------------------------------------
    unit_lines = sec.get('units', [])
    units = {}
    current = None
    mode = None
    for line in unit_lines:
        if line.startswith('@@UNIT '):
            candidate = line.split(' ', 1)[1].strip()
            # systemctl's "7 unit files listed." footer leaks into the shell loop.
            if not candidate.endswith(('.service', '.target', '.timer', '.socket',
                                       '.mount', '.path', '.slice')):
                current = None
                continue
            current = candidate
            units[current] = {'enabled': None, 'active': None, 'show': {},
                              'files': [], 'cat': []}
            mode = 'show'
            continue
        if line.startswith('@@CAT '):
            mode = 'cat'
            continue
        if current is None:
            continue
        if mode == 'show':
            if line.startswith(('FragmentPath=', 'DropInPaths=', 'UnitFileState=',
                                'WantedBy=', 'After=', 'Before=', 'ExecStart=',
                                'ConditionPathExists=')):
                key, val = line.split('=', 1)
                units[current]['show'].setdefault(key, []).append(val)
            elif line.startswith(('enabled', 'disabled', 'static', 'masked',
                                  'indirect', 'generated', 'alias', 'linked')):
                units[current]['enabled'] = line.split()[0]
            elif line.startswith(('active', 'inactive', 'failed', 'activating')):
                units[current]['active'] = line.split()[0]
        else:
            units[current]['cat'].append(line)
    for name_, unit in units.items():
        parsed = []
        for entry in unit['show'].get('ExecStart', []):
            m = re.search(r'path=([^ ;]+)', entry)
            if m:
                parsed.append({'path': m.group(1)})
        unit['exec'] = parsed
        # ExecStart property blocks appear as repeated lines; also parse fragment.
        fragment = unit['show'].get('FragmentPath', [None])[0]
        unit['fragment'] = fragment or None
        unit['drop_ins'] = [p for p in unit['show'].get('DropInPaths', []) if p]
        unit['wanted_by'] = unit['show'].get('WantedBy', [])
        unit['after'] = unit['show'].get('After', [])
        unit['before'] = unit['show'].get('Before', [])
        unit['interesting'] = bool(INTERESTING.search(name_))
    base['units'] = units

    # ---- local files ----------------------------------------------
    local_files = []
    for line in sec.get('usrlocal', []):
        if line.startswith('LOCAL '):
            bits = line.split()
            local_files.append({'path': bits[1], 'mode': bits[2],
                                'owner': bits[3], 'group': bits[4],
                                'bytes': int(bits[5]), 'sha256': bits[6]})
    base['runtime']['local_files'] = local_files
    base['runtime']['local_scripts'] = {}
    current = None
    for line in sec.get('localexec', []):
        if line.startswith('@@SKIPBINARY '):
            base['runtime']['local_scripts'][line.split()[1]] = '<binary: qbootctl ELF>'
            current = None
            continue
        if line.startswith('@@FILE '):
            current = line.split(' ', 1)[1]
            base['runtime']['local_scripts'][current] = ''
            continue
        if current:
            base['runtime']['local_scripts'][current] += line + '\n'

    base['runtime']['local_modules'] = {}
    current = None
    for line in sec.get('localko', []):
        if line.startswith('@@KO '):
            current = line.split(' ', 1)[1]
            base['runtime']['local_modules'][current] = {'modinfo': {}}
            continue
        if current is None:
            continue
        if re.match(r'^[0-9a-f]{64} ', line):
            base['runtime']['local_modules'][current]['sha256'] = line.split()[0]
        elif ':' in line:
            k, v = line.split(':', 1)
            base['runtime']['local_modules'][current]['modinfo'][k.strip()] = v.strip()

    base['packages']['installed'] = [l for l in sec.get('packagelist', []) if l]
    base['packages']['ownership'] = [l for l in sec.get('ownership', []) if l.startswith('OWN ')]

    # ---- module load order and parameters -------------------------
    loaded = []
    for line in sec.get('modules', []):
        bits = line.split()
        if len(bits) >= 4 and re.match(r'^[a-zA-Z0-9_]+$', bits[0]):
            loaded.append({'name': bits[0], 'bytes': int(bits[1]),
                           'refcount': int(bits[2]), 'used_by': [] if bits[3] == '-' else bits[3].split(',')})
    params = {}
    current = None
    for line in sec.get('modules', []):
        if line.startswith('@@MODPARAM '):
            current = line.split()[1]
            params[current] = {}
            continue
        if current and line.startswith('  '):
            key = line.strip().split('=', 1)
            params[current][key[0]] = key[1] if len(key) > 1 else ''
    base['modules'] = {'load_order': loaded, 'parameters': params}

    kmods = []
    for line in sec.get('kernelmodules', []):
        if line.startswith('KMOD '):
            bits = line.split()
            kmods.append({'path': bits[1],
                          'bytes': int(bits[3]) if bits[3].isdigit() else None,
                          'sha256': bits[4] if len(bits) > 4 and re.match(r'^[0-9a-f]{64}$', bits[4]) else None,
                          'owner': ' '.join(bits[6:]).strip() if len(bits) > 6 else None})
    base['modules']['packaged_files'] = kmods
    base['modules']['dep_files'] = [l for l in sec.get('kernelmodules', [])
                                    if l.startswith('FILE ')]
    base['modules']['blacklists'] = [l for l in sec.get('blacklists', []) if 'blacklist' in l]

    # ---- power / adc / display ------------------------------------
    psu = {}
    current = None
    for line in sec.get('power', []):
        if line.startswith('@@PSU '):
            current = line.split(' ', 1)[1]
            psu[current] = {}
            continue
        if current and '=' in line:
            k, v = line.split('=', 1)
            psu[current][k] = v
    upower = [l for l in sec.get('power', []) if l.startswith('Device:') or 'percentage:' in l
              or 'state:' in l or 'native-path:' in l]
    base['runtime']['power_supply'] = psu
    base['runtime']['upower'] = upower
    base['runtime']['iio'] = [l for l in sec.get('adc', []) if l.startswith('@@IIO')]

    base['runtime']['display'] = [l for l in sec.get('display', [])]
    base['runtime']['failed_units'] = [l for l in sec.get('services', [])
                                       if l.strip() and not l.startswith('  ')][:5]
    base['runtime']['warnings'] = [l for l in sec.get('services', [])
                                   if re.search(r'kernel:.*(warn|fail|error)', l, re.I)][:40]

    # ---- device tree ----------------------------------------------
    dt_b64 = ''.join(sec.get('dt', [])).strip()
    dt_tar = b''
    if dt_b64:
        import base64
        dt_tar = base64.b64decode(dt_b64)
        (out / 'raw' / 'device-tree.tar').write_bytes(dt_tar)
    running = parse_dt_tree(dt_tar)
    (out / 'raw' / 'running-device-tree.json').write_text(
        json.dumps({p: {k: printable(v) for k, v in props.items()}
                    for p, props in running.items()}, indent=1) + '\n')

    ref_blob = (ROOT / 'postmarketos/device/testing/device-oneplus-xigua/verified-vendor.dtb').read_bytes()
    reference = FDT(ref_blob).nodes()
    diff = dt_semantic_diff(running, reference)
    base['device_tree'] = {
        'running_nodes': len(running),
        'reference_nodes': len(reference),
        'running_root_compatible': printable(running.get('/', {}).get('compatible', b'')),
        'reference_root_compatible': printable(reference.get('/', {}).get('compatible', b'')),
        'running_root_model': printable(running.get('/', {}).get('model', b'')),
        'reference_root_model': printable(reference.get('/', {}).get('model', b'')),
        'nodes_only_running': diff['nodes_only_running'],
        'nodes_only_reference': diff['nodes_only_reference'],
        'property_changes': diff['property_changes'],
        'interesting_nodes': sorted(p for p in set(running) | set(reference)
                                    if INTERESTING.search(p)),
        'reference_sha256': sha(ref_blob),
        'reference_bytes': len(ref_blob),
    }

    # ---- gaps ------------------------------------------------------
    for path, why in ROOT_ONLY:
        base['gaps'].append({
            'item': why, 'path': path,
            'reason': 'requires root; non-interactive session has no passwordless sudo',
            'status': 'unavailable-this-run',
        })
    base['gaps'].append({
        'item': 'slot state (GPT attributes)',
        'path': '/dev/disk/by-partlabel/*',
        'reason': 'GPT block reads require root; slot attributes not re-read this run',
        'status': 'unavailable-this-run',
    })

    (out / 'baseline-manifest.json').write_text(json.dumps(base, indent=2) + '\n')
    print(json.dumps({
        'manifest': str(out / 'baseline-manifest.json'),
        'units': len(units),
        'local_files': len(local_files),
        'packaged_modules': len(kmods),
        'dt_only_running': len(diff['nodes_only_running']),
        'dt_only_reference': len(diff['nodes_only_reference']),
        'dt_changed_nodes': len(diff['property_changes']),
        'gaps': len(base['gaps']),
    }, indent=2))


if __name__ == '__main__':
    main()
