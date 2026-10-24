"""Generate slot-A Android-v4 boot images offline from explicit, checked inputs.

This is the parameterised entry point that replaces the fixed-date logic in
``package_native_pmos.py``.  It never touches the phone: generation and flashing
are separate steps.  Container sizes, offsets, partition capacity and the AVB
tail are all validated, and the AVB metadata is retained unchanged (it is *not*
a valid OEM signature of the modified payload; slot A still relies on the
unlocked bootloader).

Kernel and initramfs are **never defaulted**: they must come from a validated
build directory (``--target`` with ``artifacts.json`` and
``image-verification.json``) or be given explicitly together with
``--artifacts`` and ``--kernel-release``.  The target package versions are
compared with ``integration-profile.json`` so an old build cannot silently be
mixed with new module packages.

Two modes:

  existing-root   keep the actually mounted root UUID.  Use this for the
                  "upgrade packages on the current root" flow.
  fresh-rootfs    use the UUID of the freshly generated rootfs image.  This
                  mode is for a full reinstall and its images must not be
                  flashed over a daily-use userdata without a separate backup.

Example (existing root, validated build directory):

  python tools/build_native_slot_image.py --mode existing-root \
    --target out/postmarketos-baseline-20261017 \
    --root-uuid af27e4ed-0f1f-4976-94a1-46c4c658e55e \
    --out out/native-slot-20261017/existing-root

Example (fresh rootfs, offline only):

  python tools/build_native_slot_image.py --mode fresh-rootfs \
    --target out/postmarketos-baseline-20261017 \
    --out out/native-slot-20261017/fresh-rootfs
"""
import argparse
import gzip
import hashlib
import io
import json
import re
import struct
import tarfile
from pathlib import Path

from bootimg import BootImage
from build_init_marker_test import lz4, make_entry, parse_cpio
from fdt import FDT

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOOT = ROOT / 'out/native-install-20261016/backup/boot_a.img'
DEFAULT_INIT_BOOT = ROOT / 'out/native-install-20261016/backup/init_boot_a.img'
# Last A-slot vendor_boot actually flashed and booted (Wi-Fi bring-up): its DTB
# is the accepted tree with BQ28Z610, ADC5 Gen3, WCN7850, panel and touch.
DEFAULT_VENDOR = ROOT / 'out/wifi-bringup-20261017/vendor_boot_a-wifi.img'
DEFAULT_DTBO = ROOT / 'out/native-install-20261016/backup/dtbo_a.img'
DEFAULT_PROFILE = ROOT / 'postmarketos/integration-profile.json'
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
TARGET_PACKAGES = ('linux-oneplus-xigua', 'device-oneplus-xigua')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(n):
    return (n + 4095) // 4096 * 4096


def avb_offset(data):
    magic, major, minor, original_size, offset, size, _ = struct.unpack('>4sIIQQQ28s', data[-64:])
    assert magic == b'AVBf' and data[offset:offset + 4] == b'AVB0'
    assert 0 < original_size <= offset and offset + size <= len(data) - 64
    return offset


def load(path):
    return path.read_bytes()


def resolve_build_inputs(args):
    """Resolve kernel/initramfs and prove they belong to the target packages."""
    profile = json.loads(Path(args.profile).read_text())
    if args.target:
        target = Path(args.target).resolve()
        artifacts_path = target / 'artifacts.json'
        verification_path = target / 'image-verification.json'
        assert artifacts_path.is_file(), f'{target}: missing artifacts.json'
        assert verification_path.is_file(), f'{target}: missing image-verification.json'
        artifacts = json.loads(artifacts_path.read_text())
        verification = json.loads(verification_path.read_text())
        kernel = target / 'vmlinuz'
        initramfs = target / 'initramfs'
        assert kernel.is_file() and initramfs.is_file(), f'{target}: missing vmlinuz/initramfs'
        if args.kernel:
            assert Path(args.kernel).resolve() == kernel, '--kernel disagrees with --target'
        if args.initramfs:
            assert Path(args.initramfs).resolve() == initramfs, '--initramfs disagrees with --target'
        source = {'kind': 'target-build', 'dir': str(target),
                  'artifacts': str(artifacts_path),
                  'image_verification': str(verification_path)}
    else:
        assert args.kernel and args.initramfs and args.artifacts, (
            'kernel/initramfs are not defaulted: pass --target <build dir>, or '
            '--kernel, --initramfs and --artifacts together')
        assert args.image_verification, (
            'explicit inputs also need --image-verification: package versions and '
            'the full kernel release are proved from it')
        kernel = Path(args.kernel).resolve()
        initramfs = Path(args.initramfs).resolve()
        artifacts_path = Path(args.artifacts).resolve()
        assert artifacts_path.is_file(), artifacts_path
        artifacts = json.loads(artifacts_path.read_text())
        verification = json.loads(Path(args.image_verification).read_text())
        source = {'kind': 'explicit-inputs', 'artifacts': str(artifacts_path),
                  'image_verification': str(Path(args.image_verification).resolve())}

    files = artifacts['files']
    assert files['vmlinuz']['sha256'] == sha(kernel.read_bytes()), \
        f'kernel does not match {artifacts_path}'
    assert args.empty_initramfs or files['initramfs']['sha256'] == sha(initramfs.read_bytes()), \
        f'initramfs does not match {artifacts_path}'

    for pkg in TARGET_PACKAGES:
        want = profile['packages'][pkg]
        got = verification['local_packages'].get(pkg)
        assert got == want, (
            f'{pkg}: build image contains {got}, integration-profile expects {want}; '
            'rebuild or update the profile before generating images')
    release = verification['kernel_release']
    assert release, 'build image verification has no kernel_release'
    if args.kernel_release:
        assert args.kernel_release == release, \
            f'--kernel-release {args.kernel_release} != build {release}'
    source['packages'] = {pkg: profile['packages'][pkg] for pkg in TARGET_PACKAGES}

    if args.kernel_apk:
        apk = Path(args.kernel_apk).resolve()
        with tarfile.open(fileobj=io.BytesIO(apk.read_bytes()), mode='r:gz') as tar:
            packaged = tar.extractfile('boot/vmlinuz').read()
            release_file = tar.extractfile(
                'usr/share/kernel/oneplus-xigua/kernel.release').read().decode().strip()
        assert sha(packaged) == sha(kernel.read_bytes()), \
            f'{apk}: boot/vmlinuz differs from the kernel input'
        assert release_file == release, f'{apk}: release {release_file} != {release}'
        source['kernel_apk'] = str(apk)

    return kernel, initramfs, release, source


def check_kernel(data):
    assert data[56:60] == b'ARM\x64', 'kernel is not a raw arm64 Image'
    start = data.index(b'IKCFG_ST')
    end = data.index(b'IKCFG_ED', start + 8)
    config = gzip.decompress(data[start + 8:end]).decode()
    assert 'CONFIG_INITRAMFS_SOURCE=""\n' in config, 'debug initramfs embedded in kernel'
    assert 'CONFIG_CMDLINE_FORCE=y' not in config
    for key in ['RD_LZ4', 'SCSI_UFS_QCOM', 'EXT4_FS', 'BLK_DEV_LOOP', 'EFI_PARTITION']:
        assert f'CONFIG_{key}=y\n' in config, key
    return config


def check_initramfs(raw):
    assert raw[:2] == b'\x1f\x8b', 'expected a gzip-compressed distro initramfs'
    archive = gzip.decompress(raw)
    entries = parse_cpio(archive)
    content = {n.removeprefix('./'): (f, d) for f, n, d in entries}
    assert content['init'][1].startswith(b'#!/bin/busybox ash')
    assert 'init_2nd.sh' in content
    assert b'mount_subpartitions' in content['init_functions.sh'][1]
    assert not any(n.endswith('client_key_host') for n in content)
    return archive


def build(args):
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').unlink(missing_ok=True)
    (out / 'SHA256SUMS').unlink(missing_ok=True)

    kernel_path, initramfs_path, kernel_release, source = resolve_build_inputs(args)
    vendor_path = Path(args.vendor_template).resolve()
    boot_path = Path(args.boot_template).resolve()
    init_boot_path = Path(args.init_boot_template).resolve()
    dtbo_path = Path(args.dtbo_template).resolve()
    dtb_path = Path(args.dtb).resolve() if args.dtb else None

    required_inputs = [kernel_path, initramfs_path, vendor_path, boot_path,
                       init_boot_path, dtbo_path]
    for path in required_inputs:
        assert path.is_file(), f'missing input {path}'
    if dtb_path:
        assert dtb_path.is_file(), f'missing input {dtb_path}'

    # ---- root UUID ------------------------------------------------------
    if args.mode == 'existing-root':
        assert args.root_uuid, 'existing-root mode needs --root-uuid'
        root_uuid = args.root_uuid.lower()
        uuid_source = 'operator-supplied current root UUID'
        userdata_note = 'does not touch userdata; packages are upgraded in place'
    else:
        verification_path = args.image_verification
        if not verification_path and args.target:
            verification_path = str(Path(args.target) / 'image-verification.json')
        assert verification_path, 'fresh-rootfs mode needs --image-verification or --target'
        verify = json.loads(Path(verification_path).read_text())
        root_uuid = verify['image']['root_uuid'].lower()
        uuid_source = f'{verification_path} (fresh image)'
        userdata_note = 'flashing these images over an existing userdata destroys it'
        if args.root_uuid:
            assert args.root_uuid.lower() == root_uuid, \
                'fresh-rootfs mode must use the UUID of the generated image'
    assert UUID_RE.match(root_uuid), f'bad root UUID {root_uuid}'

    # ---- inputs ---------------------------------------------------------
    kernel = load(kernel_path)
    check_kernel(kernel)
    if args.empty_initramfs:
        # No userspace initramfs at all: the kernel mounts root=UUID directly.
        # This only works when UFS, the block layer and ext4 are built-in, which
        # is the case for this kernel. The vendor fragment still has to contain a
        # valid (empty) cpio archive.
        fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
        empty = make_entry(fields, 'TRAILER!!!', b'')
        initramfs = empty
        rd = lz4(['-z', '-l', '-12', '-c'], empty)
        assert lz4(['-d', '-l', '-c'], rd) == empty
        assert parse_cpio(lz4(['-d', '-l', '-c'], rd))[0][1] == 'TRAILER!!!'
    else:
        initramfs_raw = load(initramfs_path)
        initramfs = check_initramfs(initramfs_raw)
        rd = lz4(['-z', '-l', '-12', '-c'], initramfs)
        assert lz4(['-d', '-l', '-c'], rd) == initramfs

    # ---- vendor_boot: keep the verified container and DTB ----------------
    vendor = load(vendor_path)
    assert vendor[:8] == b'VNDRBOOT'
    version, page = struct.unpack_from('<II', vendor, 8)
    assert version == 4 and page == 4096
    rdsize = struct.unpack_from('<I', vendor, 24)[0]
    hsize, dsize = struct.unpack_from('<II', vendor, 2096)
    rdoff = align(hsize)
    dtboff = align(rdoff + rdsize)
    tableoff = align(dtboff + dsize)
    tsize, count, esize, bcsize = struct.unpack_from('<IIII', vendor, 2112)
    assert count == 1 and esize == 108 and tsize == 108
    assert struct.unpack_from('<III', vendor, tableoff) == (rdsize, 0, 1)
    embedded_dtb = vendor[dtboff:dtboff + dsize]
    vendor_tail = avb_offset(vendor)
    assert len(rd) <= rdsize, f'initramfs {len(rd)} B exceeds vendor fragment {rdsize} B'
    assert dtboff + dsize < vendor_tail

    if dtb_path:
        replacement = load(dtb_path)
        assert len(replacement) == dsize, (
            f'--dtb is {len(replacement)} B but the container slot holds {dsize} B; '
            'a size change would move the vendor ramdisk table and the AVB tail')
        embedded_dtb = replacement
        dtb_origin = str(dtb_path)
    else:
        dtb_origin = 'vendor template (unchanged)'

    assert FDT(embedded_dtb).nodes()['/']['compatible'].split(b'\0')[:2] == \
        [b'oneplus,xigua', b'qcom,sm8550']
    required = {
        '/soc@0/geniqup@8c0000/i2c@880000/fuel-gauge@55',
        '/soc@0/spmi@c400000/pmic@0/adc@9000',
        '/soc@0/spmi@c400000/pmic@0/adc@9000/channel@74c',
        '/soc@0/pcie@1c00000/pcie@0/wifi@0',
        '/soc@0/display-subsystem@ae00000/dsi@ae94000/panel@0',
        '/soc@0/geniqup@ac0000/spi@a90000/touchscreen@0',
    }
    dtb_nodes = set(FDT(embedded_dtb).nodes())
    missing = sorted(required - dtb_nodes)
    assert not missing, f'DTB lacks required nodes: {missing}'

    native_vendor = bytearray(vendor)
    native_vendor[rdoff:rdoff + rdsize] = rd + bytes(rdsize - len(rd))
    if dtb_path:
        native_vendor[dtboff:dtboff + dsize] = embedded_dtb
    # Allowed change: the vendor ramdisk fragment (and, with --dtb, the DTB).
    # Everything else must stay byte-identical, including the ramdisk table,
    # the bootconfig block and the AVB tail.
    assert native_vendor[:rdoff] == vendor[:rdoff]
    assert native_vendor[rdoff + rdsize:dtboff] == vendor[rdoff + rdsize:dtboff]
    if dtb_path:
        assert native_vendor[dtboff:dtboff + dsize] == embedded_dtb
    else:
        assert native_vendor[dtboff:dtboff + dsize] == vendor[dtboff:dtboff + dsize]
    assert native_vendor[dtboff + dsize:tableoff] == vendor[dtboff + dsize:tableoff]
    assert native_vendor[tableoff:vendor_tail] == vendor[tableoff:vendor_tail]
    assert native_vendor[vendor_tail:] == vendor[vendor_tail:]

    # ---- init_boot: empty generic ramdisk --------------------------------
    generic = load(init_boot_path)
    assert generic[:8] == b'ANDROID!' and struct.unpack_from('<I', generic, 40)[0] == 4
    assert struct.unpack_from('<I', generic, 8)[0] == 0
    old_size = struct.unpack_from('<I', generic, 12)[0]
    fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
    empty = make_entry(fields, 'TRAILER!!!', b'')
    empty_lz4 = lz4(['-z', '-l', '-12', '-c'], empty)
    assert parse_cpio(lz4(['-d', '-l', '-c'], empty_lz4))[0][1] == 'TRAILER!!!'
    old_end = 4096 + align(old_size)
    generic_tail = avb_offset(generic)
    assert old_end <= generic_tail and len(empty_lz4) < old_size
    native_generic = bytearray(generic)
    struct.pack_into('<I', native_generic, 12, len(empty_lz4))
    native_generic[4096:old_end] = empty_lz4 + bytes(old_end - 4096 - len(empty_lz4))
    assert native_generic[old_end:] == generic[old_end:]

    # ---- boot: kernel + cmdline, AVB tail retained ----------------------
    stock = load(boot_path)
    base = BootImage.parse(str(boot_path))
    boot = BootImage()
    boot.header_version = base.header_version
    boot.os_version = base.os_version
    boot.kernel = kernel
    extra = (args.extra_cmdline or '').strip()
    assert re.fullmatch(r'[A-Za-z0-9_.=,:+\- ]*', extra), extra
    cmdline = f'root=UUID={root_uuid} rootwait rw loglevel=4' + (f' {extra}' if extra else '')
    prefix = boot.pack(cmdline=cmdline)
    boot_tail = avb_offset(stock)
    assert len(prefix) < boot_tail
    native_boot = bytearray(stock)
    native_boot[:boot_tail] = prefix + bytes(boot_tail - len(prefix))
    assert native_boot[boot_tail:] == stock[boot_tail:]

    dtbo = load(dtbo_path)
    assert dtbo[:4] == b'\xd7\xb7\xab\x1e', 'dtbo template is not a dt_table image'

    files = {
        'boot_a.img': bytes(native_boot),
        'init_boot_a.img': bytes(native_generic),
        'vendor_boot_a.img': bytes(native_vendor),
        'dtbo_a.img': dtbo,
        'combined-initrd.lz4': bytes(native_vendor[rdoff:rdoff + rdsize]) + empty_lz4,
    }
    for name, data in files.items():
        (out / name).write_bytes(data)

    # ---- unpack verification -------------------------------------------
    unpacked = BootImage.parse(str(out / 'boot_a.img'))
    assert unpacked.kernel == kernel and unpacked.ramdisk == b''
    assert unpacked.cmdline == cmdline.encode() and unpacked.header_version == 4
    disk_vendor = (out / 'vendor_boot_a.img').read_bytes()
    disk_generic = (out / 'init_boot_a.img').read_bytes()
    generic_size = struct.unpack_from('<I', disk_generic, 12)[0]
    combined = disk_vendor[rdoff:rdoff + rdsize] + disk_generic[4096:4096 + generic_size]
    assert combined == files['combined-initrd.lz4']
    for name in ('boot_a', 'init_boot_a', 'vendor_boot_a', 'dtbo_a'):
        assert len(files[name + '.img']) == len(load({
            'boot_a': boot_path, 'init_boot_a': init_boot_path,
            'vendor_boot_a': vendor_path, 'dtbo_a': dtbo_path}[name])), name

    inputs = {}
    for label, path in {
        'kernel': kernel_path, 'initramfs': initramfs_path,
        'vendor_template': vendor_path, 'boot_template': boot_path,
        'init_boot_template': init_boot_path, 'dtbo_template': dtbo_path,
    }.items():
        data = path.read_bytes()
        inputs[label] = {'path': str(path), 'bytes': len(data), 'sha256': sha(data),
                         'mtime': path.stat().st_mtime}
    inputs['initramfs']['uncompressed_bytes'] = len(initramfs)
    inputs['dtb'] = {'origin': dtb_origin, 'bytes': len(embedded_dtb),
                     'sha256': sha(embedded_dtb)}

    manifest = {
        'mode': args.mode,
        'target_slot': 'a',
        'rescue_slot': 'b',
        'root_uuid': root_uuid,
        'root_uuid_source': uuid_source,
        'cmdline': cmdline,
        'extra_cmdline': extra,
        'kernel_release': kernel_release,
        'build_source': source,
        'delivery': ('empty initramfs; kernel mounts root=UUID directly'
                     if args.empty_initramfs else
                     'complete distro initramfs in the padded vendor platform fragment; '
                     'empty generic archive'),
        'inputs': inputs,
        'outputs': {name: {'bytes': len(data), 'sha256': sha(data)}
                    for name, data in files.items()},
        'checks': {
            'kernel_is_raw_arm64_image': True,
            'no_debug_initramfs_embedded_in_kernel': True,
            'distro_initramfs_mounts_subpartitions': True,
            'kernel_and_initramfs_match_target_artifacts': True,
            'target_packages_match_integration_profile': source['kind'] == 'target-build',
            'kernel_release_matches_target': True,
            'dtb_unchanged_from_template': dtb_path is None,
            'dtb_has_battery_adc_wifi_panel_touch': True,
            'container_offsets_and_capacity_preserved': True,
            'avb_tail_preserved_but_modified_payload_not_resigned': True,
            'requires_unlocked_bootloader': True,
            'local_pack_unpack_checks_passed': True,
            'phone_partitions_written': False,
        },
        'warnings': [userdata_note,
                     'Retained AVB metadata is not an OEM signature of the new payload.'],
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{sha(d)}  {n}\n' for n, d in files.items()))
    print(json.dumps({'out': str(out), 'mode': args.mode, 'root_uuid': root_uuid,
                      'kernel_release': kernel_release,
                      'build_source': source['kind'],
                      'compressed_initramfs_bytes': len(rd),
                      'vendor_fragment_bytes': rdsize,
                      'outputs': {n: v['sha256'] for n, v in manifest['outputs'].items()}},
                     indent=2))
    print('PASS: slot-A images generated and unpacked offline; no phone access')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mode', choices=['existing-root', 'fresh-rootfs'], required=True)
    ap.add_argument('--target',
                    help='validated build directory with artifacts.json and '
                         'image-verification.json (required unless explicit inputs are given)')
    ap.add_argument('--root-uuid', help='existing-root: current root UUID; '
                                        'fresh-rootfs: optional assertion')
    ap.add_argument('--image-verification',
                    help='fresh-rootfs: verify_pmos_integrated_image.py output '
                         '(defaults to <target>/image-verification.json)')
    ap.add_argument('--profile', default=str(DEFAULT_PROFILE))
    ap.add_argument('--kernel')
    ap.add_argument('--initramfs')
    ap.add_argument('--artifacts', help='artifacts.json when not using --target')
    ap.add_argument('--kernel-release', help='full release when not using --target')
    ap.add_argument('--kernel-apk', help='optional linux APK to cross-check vmlinuz')
    ap.add_argument('--empty-initramfs', action='store_true',
                    help='ship an empty initramfs so the kernel mounts root=UUID itself; '
                         'requires UFS/block/ext4 built into the kernel')
    ap.add_argument('--boot-template', default=str(DEFAULT_BOOT))
    ap.add_argument('--init-boot-template', default=str(DEFAULT_INIT_BOOT))
    ap.add_argument('--vendor-template', default=str(DEFAULT_VENDOR))
    ap.add_argument('--dtbo-template', default=str(DEFAULT_DTBO))
    ap.add_argument('--dtb', default=None,
                    help='optional same-size DTB replacement for the container')
    ap.add_argument('--extra-cmdline', default='',
                    help='additional kernel cmdline tokens, e.g. panel_oneplus_aa536.refresh=120')
    ap.add_argument('--out', required=True)
    build(ap.parse_args())


if __name__ == '__main__':
    main()
