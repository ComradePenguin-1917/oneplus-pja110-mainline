"""Preserve the verified local image independently of pmbootstrap chroots."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--export', default='/tmp/postmarketOS-export')
parser.add_argument('--out-dir', default='out/postmarketos-baseline-20261017')
parser.add_argument('--force', action='store_true',
                    help='replace an existing archive after a deliberate rebuild')
options = parser.parse_args()

win = Path('/mnt/h/workspace/PJA110-Mainline')
out = win / options.out_dir
out.mkdir(parents=True, exist_ok=True)
export = Path(options.export)
verification = json.loads((out / 'image-verification.json').read_text())
source = export / 'oneplus-xigua.img'
assert str(source.resolve()) == verification['image']['image']
assert source.stat().st_size == verification['image']['bytes']
destination = out / 'oneplus-xigua.img.gz'
assert options.force or not destination.exists(), 'Archive exists; inspect before replacing'
partial = destination.with_suffix('.gz.partial')
assert not partial.exists(), 'Partial archive exists; inspect first'
raw = hashlib.sha256()
with source.open('rb') as inp, partial.open('xb') as output:
    with gzip.GzipFile(filename='', mode='wb', compresslevel=1, fileobj=output, mtime=0) as compressed:
        for block in iter(lambda: inp.read(4*1024*1024), b''):
            raw.update(block)
            compressed.write(block)
partial.replace(destination)

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            result.update(block)
    return result.hexdigest()

files = {}
for name in ('vmlinuz', 'initramfs'):
    shutil.copyfile(export / name, out / name)
    files[name] = {'bytes': (out / name).stat().st_size, 'sha256': digest(out / name)}
files[destination.name] = {'bytes': destination.stat().st_size, 'sha256': digest(destination),
                           'uncompressed_bytes': source.stat().st_size, 'uncompressed_sha256': raw.hexdigest()}
record = {'files': files, 'image_contents_verification': 'image-verification.json',
          'phone_partitions_written': False, 'native_phone_boot_verified': False}
(out / 'artifacts.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
