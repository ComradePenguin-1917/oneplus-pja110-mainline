"""Correct stock DTBO root identity without changing board selection data."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
from fdt import DTBO, FDT

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'out/native-install-20261017/charger-startup/dtbo_a.img'
OUT = ROOT / 'out/native-install-20261017/dtbo-mainline-identity'

def prepare():
    OUT.mkdir(exist_ok=True)
    original = SOURCE.read_bytes()
    candidate = bytearray(original)
    expected = b'oneplus,xigua\0qcom,sm8550\0'
    entries = list(DTBO(original).entries())
    changes = []
    for entry in entries:
        before = FDT(entry['blob']).nodes()
        assert before['/']['compatible'] == b'qcom,kalama-mtp\0qcom,kalama\0qcom,mtp\0'
        path = OUT / ('entry-%d.dtb' % entry['index'])
        path.write_bytes(entry['blob'])
        wslpath = '/mnt/h/' + path.relative_to(Path('H:/')).as_posix()
        subprocess.run(['wsl.exe', '-d', 'Ubuntu-22.04', '--', 'fdtput',
                        '-t', 's', wslpath, '/', 'compatible',
                        'oneplus,xigua', 'qcom,sm8550'], check=True)
        edited = path.read_bytes()
        after = FDT(edited).nodes()
        diff = {(p, k) for p in before.keys() | after.keys()
                for k in before.get(p, {}).keys() | after.get(p, {}).keys()
                if before.get(p, {}).get(k) != after.get(p, {}).get(k)}
        assert diff == {('/', 'compatible')}, diff
        assert after['/']['compatible'] == expected
        assert FDT(entry['blob']).reserved_memory() == FDT(edited).reserved_memory()
        assert len(edited) <= entry['size']
        padded = bytearray(edited.ljust(entry['size'], b'\0'))
        struct.pack_into('>I', padded, 4, entry['size'])
        assert FDT(padded).nodes() == after
        start = entry['offset']
        candidate[start:start + entry['size']] = padded
        changes.append({'index': entry['index'], 'offset': start,
                        'size': entry['size'], 'changed_property': '/:compatible'})
    # Verify container metadata and every byte outside its DTBs remain identical.
    end = 0
    for entry in sorted(entries, key=lambda e: e['offset']):
        start = entry['offset']
        assert candidate[end:start] == original[end:start]
        end = start + entry['size']
    assert candidate[end:] == original[end:]
    assert len(candidate) == len(original)
    for entry in DTBO(candidate).entries():
        assert FDT(entry['blob']).nodes()['/']['compatible'] == expected
    target = OUT / 'dtbo_a.img'
    target.write_bytes(candidate)
    report = {'source': str(SOURCE), 'source_sha256': hashlib.sha256(original).hexdigest(),
              'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
              'bytes': len(candidate), 'entries': changes,
              'only_root_compatible_changed': True,
              'container_metadata_and_other_bytes_preserved': True,
              'phone_written': False, 'runtime_verified': False}
    (OUT / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    prepare()
