"""Archive obsolete project documents/tools with verified, reversible manifests.

The Windows plan is explicit in out/maintenance-20261017/tools-retained.json.
WSL archives only the reviewed obsolete experiment directories. Third-party
source trees, firmware, package caches, backups and phone storage are excluded.
"""
import argparse
import hashlib
import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

STAMP = 'maintenance-20261017'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def safe(root, path):
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    if path.is_symlink():
        raise RuntimeError('Refusing symlink target: ' + str(path))
    return resolved


def windows(apply):
    root = Path(__file__).resolve().parents[1]
    evidence = root / 'out' / STAMP
    keep = set(json.loads((evidence / 'tools-retained.json').read_text()))
    keep.update({'device_status.py', 'maintain_workspace.py'})
    assert all((root / 'tools' / name).is_file() for name in keep)
    files = sorted(p for p in (root / 'tools').iterdir() if p.is_file() and p.name not in keep)
    files += sorted(p for p in (root / 'docs').iterdir() if p.is_file())
    files += [p for p in [root / 'postmarketos/README.md', root / 'temp-aston-kernel.sh'] if p.is_file()]
    archive_dir = root / 'archive' / STAMP
    archive = archive_dir / 'windows-history.zip'
    assert not archive.exists(), 'This cleanup has already been archived; inspect manifest before rerunning'
    record = {p.relative_to(root).as_posix(): {'bytes': p.stat().st_size, 'sha256': digest(p)} for p in files}
    result = dict(platform='Windows', archived_files=len(files), retained_tool_files=len(keep),
                  archive=str(archive), files=record)
    (evidence / 'windows-cleanup-plan.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))
    if not apply:
        return
    archive_dir.mkdir(parents=True, exist_ok=True)
    partial = archive.with_suffix('.zip.partial')
    with zipfile.ZipFile(partial, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in files:
            safe(root, p)
            z.write(p, p.relative_to(root).as_posix())
    with zipfile.ZipFile(partial) as z:
        for name, info in record.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == info['sha256'], name
    partial.replace(archive)
    for p in files:
        safe(root, p)
        assert digest(p) == record[p.relative_to(root).as_posix()]['sha256']
        p.unlink()
    result['archive_sha256'] = digest(archive)
    result['completed'] = True
    (archive_dir / 'windows-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    (evidence / 'windows-cleanup-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Archived contents verified, obsolete originals removed; retained tools:', len(keep))


def wsl(apply):
    assert os.name != 'nt'
    root = (Path.home() / 'workspace/PJA110-Mainline').resolve()
    win = Path('/mnt/h/workspace/PJA110-Mainline')
    evidence = win / 'out' / STAMP
    candidates = json.loads((evidence / 'wsl-candidates.json').read_text())
    names = [r['name'] for r in candidates if r['exists'] and not r['mentioned_by_retained_tools']]
    assert names and all('/' not in name and name not in {'.', '..'} for name in names)
    files = {}
    for name in names:
        directory = safe(root, root / name)
        assert directory.is_dir() and not directory.is_mount(), directory
        for p in directory.rglob('*'):
            if p.is_file() and not p.is_symlink():
                safe(root, p)
                files[p.relative_to(root).as_posix()] = {'bytes': p.stat().st_size, 'sha256': digest(p)}
    dest = root / 'archive' / STAMP
    archive = dest / 'wsl-experiments.tar.gz'
    assert not archive.exists(), 'Inspect existing WSL archive before rerunning'
    result = dict(platform='WSL', archived_directories=names, archived_files=len(files),
                  archive=str(archive), files=files)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))
    if not apply:
        return
    dest.mkdir(parents=True, exist_ok=True)
    partial = archive.with_suffix('.gz.partial')
    with tarfile.open(partial, 'x:gz') as t:
        for name in names:
            t.add(root / name, arcname=name, recursive=True)
    with tarfile.open(partial, 'r:gz') as t:
        for name, info in files.items():
            assert hashlib.sha256(t.extractfile(name).read()).hexdigest() == info['sha256'], name
    partial.replace(archive)
    for name in names:
        directory = safe(root, root / name)
        for p in directory.rglob('*'):
            if p.is_file() and not p.is_symlink():
                assert digest(p) == files[p.relative_to(root).as_posix()]['sha256']
        shutil.rmtree(directory)
    result.update(completed=True, archive_sha256=digest(archive))
    (dest / 'wsl-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    (evidence / 'wsl-cleanup-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('WSL archive verified; obsolete experiment directories removed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('platform', choices=['windows', 'wsl'])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    {'windows': windows, 'wsl': wsl}[args.platform](args.apply)
