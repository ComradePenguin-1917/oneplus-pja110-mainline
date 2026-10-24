"""Apply a build-only workaround for mkinitfs Go faults under host QEMU."""
from pathlib import Path

root = Path.home() / 'workspace/PJA110-Mainline/pmbootstrap/pmb'
original = '    pmb.chroot.root(["mkinitfs"], chroot)'
serial = '    pmb.chroot.root(["mkinitfs"], chroot, env={"GOMAXPROCS": "1"})'
replacement = '    pmb.chroot.root(["mkinitfs"], chroot, env={"GOMAXPROCS": "1", "GOGC": "off"})'
sources = [root / 'chroot/initfs.py', root / 'install/_install.py']
# Both entry points matter: the latter regenerates initramfs after fstab UUIDs
# are known. Do not skip it or reuse the earlier initramfs with old UUIDs.
updates = []
for source in sources:
    text = source.read_text()
    if replacement in text:
        assert text.count(replacement) == 1, source
        print('mkinitfs build-only workaround already present:', source)
    else:
        previous = serial if serial in text else original
        assert text.count(previous) == 1, 'Upstream changed; inspect: ' + str(source)
        backup = source.with_suffix('.py.before-pja110-no-gc')
        if backup.exists():
            assert backup.read_text() == text, 'Backup differs; inspect: ' + str(backup)
        updates.append((source, text, previous, backup))
for source, text, previous, backup in updates:
    if not backup.exists():
        backup.write_text(text)
    source.write_text(text.replace(previous, replacement))
    print('Applied build-only GOMAXPROCS=1 GOGC=off; original saved:', backup)

# Guard against another direct invocation silently missing these parameters.
import ast
calls = []
for source in root.rglob('*.py'):
    tree = ast.parse(source.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, (ast.List, ast.Tuple)) or not first.elts:
            continue
        if not isinstance(first.elts[0], ast.Constant) or first.elts[0].value != 'mkinitfs':
            continue
        env = next((kw.value for kw in node.keywords if kw.arg == 'env'), None)
        assert env is not None, 'Unpatched mkinitfs invocation: ' + str(source)
        assert ast.literal_eval(env) == {'GOMAXPROCS': '1', 'GOGC': 'off'}, source
        calls.append(str(source.relative_to(root)))
assert sorted(calls) == ['chroot/initfs.py', 'install/_install.py'], calls
print('PASS: both direct mkinitfs call sites covered; post-fstab regeneration preserved')
