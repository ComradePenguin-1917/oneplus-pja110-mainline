"""Ordinary-user WSL preparation of the native userdata image; no phone access."""
from pathlib import Path
import gzip
import hashlib
import json
import shutil
import struct
import subprocess
import zlib
import argparse

BASE=Path('/mnt/h/workspace/PJA110-Mainline')
OUT=BASE/'out/native-install-20261017/rootfs-integrated'
WORK=Path.home()/'workspace/PJA110-Mainline/native-rootfs-work-integrated'
SOURCE=Path.home()/'workspace/PJA110-Mainline/pmbootstrap-work/chroot_native/home/pmos/rootfs/oneplus-xigua.img'
ROOT_IMAGE=WORK/'root.ext4'
DISK=WORK/'userdata-prefix.img'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def debug(cmd):
    p=subprocess.run(['debugfs','-R',cmd,str(ROOT_IMAGE)],capture_output=True)
    p.check_returncode()
    return p.stdout.decode(errors='replace')


def build(ref):
    public=(BASE/'out/usb-ncm-20261013/ssh/client_key_host.pub').read_text().strip()
    assert public.startswith('ssh-ed25519 ') and '\n' not in public
    assert 'penguin:x:10000:10000:' in debug('cat /etc/passwd')
    key=WORK/'authorized_keys'
    listing=debug('ls -p /home/penguin/.ssh')
    exists='authorized_keys' in listing
    previous=debug('cat /home/penguin/.ssh/authorized_keys').splitlines() if exists else []
    if public not in previous:
        previous.append(public)
    key.write_text('\n'.join(previous)+'\n')
    script=WORK/'add-public-key.debugfs'
    script.write_text('\n'.join([
        *(['mkdir /home/penguin/.ssh'] if not listing.strip() else []),
        *(['rm /home/penguin/.ssh/authorized_keys'] if exists else []),
        f'write {key} /home/penguin/.ssh/authorized_keys',
        'set_inode_field /home/penguin/.ssh uid 10000',
        'set_inode_field /home/penguin/.ssh gid 10000',
        'set_inode_field /home/penguin/.ssh mode 040700',
        'set_inode_field /home/penguin/.ssh/authorized_keys uid 10000',
        'set_inode_field /home/penguin/.ssh/authorized_keys gid 10000',
        'set_inode_field /home/penguin/.ssh/authorized_keys mode 0100600',
    ])+'\n')
    p=subprocess.run(['debugfs','-w','-f',str(script),str(ROOT_IMAGE)],capture_output=True)
    p.check_returncode()
    assert public in debug('cat /home/penguin/.ssh/authorized_keys').splitlines()
    stats=debug('stat /home/penguin/.ssh/authorized_keys')
    assert '10000' in stats and '0600' in stats
    (OUT/'public-key-inode.txt').write_text(stats)
    native=Path.home()/'workspace/PJA110-Mainline/pmbootstrap-work/chroot_native'
    loader=native/'usr/lib/ld-musl-x86_64.so.1'
    checker=native/'usr/bin/e2fsck'
    assert loader.is_file() and checker.is_file()
    p=subprocess.run([str(loader),'--library-path',str(native/'usr/lib'),
                      str(checker),'-f','-n',str(ROOT_IMAGE)],capture_output=True)
    (OUT/'root-e2fsck.txt').write_bytes(p.stdout+p.stderr)
    assert p.returncode==0, 'Offline root filesystem check failed'

    shutil.copyfile(SOURCE,DISK)
    part=next(p for p in ref['image']['partitions'] if p['label']=='pmOS_root')
    with DISK.open('r+b') as dst,ROOT_IMAGE.open('rb') as src:
        dst.seek(part['start']*4096)
        shutil.copyfileobj(src,dst,4*1024*1024)
    size=json.loads((BASE/'out/native-install-20261016/partitions.json').read_text())['userdata']['bytes']
    assert size%4096==0 and size>DISK.stat().st_size
    blocks=size//4096
    with DISK.open('r+b') as f:
        mbr=bytearray(f.read(4096))
        assert mbr[510:512]==b'\x55\xaa' and mbr[450]==0xee
        # Protective MBR LBAs follow this image's 4096-byte logical sectors.
        assert struct.unpack_from('<I',mbr,454)[0]==1
        struct.pack_into('<I',mbr,458,min(blocks-1,0xffffffff))
        f.seek(4096);header=bytearray(f.read(4096))
        assert header[:8]==b'EFI PART'
        hsize=struct.unpack_from('<I',header,12)[0]
        table_lba,count,entrysize=struct.unpack_from('<QII',header,72)
        table_bytes=count*entrysize
        table_sectors=(table_bytes+4095)//4096
        f.seek(table_lba*4096);table=f.read(table_sectors*4096)
        assert zlib.crc32(table[:table_bytes])==struct.unpack_from('<I',header,88)[0]
        # Keep both existing partition extents. Only disk geometry/backup moves.
        struct.pack_into('<Q',header,32,blocks-1)
        struct.pack_into('<Q',header,48,blocks-table_sectors-2)
        def checksum(h):
            struct.pack_into('<I',h,16,0)
            struct.pack_into('<I',h,16,zlib.crc32(h[:hsize]))
        checksum(header)
        backup=bytearray(header)
        struct.pack_into('<QQ',backup,24,blocks-1,1)
        struct.pack_into('<Q',backup,72,blocks-table_sectors-1)
        checksum(backup)
        old_blocks=DISK.stat().st_size//4096
        f.seek((old_blocks-table_sectors-1)*4096)
        f.write(bytes((table_sectors+1)*4096))
        f.seek(0);f.write(mbr)
        f.seek(4096);f.write(header)
    tail=table+backup
    (OUT/'userdata-backup-gpt.bin').write_bytes(tail)
    prefix_sha=sha(DISK)
    compressed=OUT/'userdata-prefix.img.gz'
    with DISK.open('rb') as src,gzip.open(compressed,'wb',compresslevel=1) as dst:
        shutil.copyfileobj(src,dst,4*1024*1024)
    # Sparse full-size disk is only for offline/QEMU geometry validation.
    full=WORK/'userdata-full.img'
    shutil.copyfile(DISK,full)
    with full.open('r+b') as f:
        f.truncate(size);f.seek(size-len(tail));f.write(tail)
    from pmos_image_info import inspect_image
    info=inspect_image(full)
    assert info['root_uuid']==ref['image']['root_uuid']
    assert [(p['start'],p['sectors'],p['uuid']) for p in info['partitions']]==[(p['start'],p['sectors'],p['uuid']) for p in ref['image']['partitions']]
    record={'userdata_bytes':size,'sector_size':4096,'prefix_bytes':DISK.stat().st_size,
            'prefix_sha256':prefix_sha,'compressed_sha256':sha(compressed),
            'compressed_bytes':compressed.stat().st_size,
            'tail_offset':size-len(tail),'tail_bytes':len(tail),
            'tail_sha256':hashlib.sha256(tail).hexdigest(),
            'root_uuid':info['root_uuid'],'root_partition_sha256':sha(ROOT_IMAGE),
            'public_key_added_for':'penguin','root_login_changed':False,
            'user_password_changed':False,'rootfs_capacity_expanded':False,
            'qemu_disk':str(full),'phone_partitions_written':False}
    (OUT/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    print('PASS: public key, offline ext4 check, unchanged UUIDs and full userdata geometry')
    print('Prepared compressed prefix plus relocated backup GPT; no phone writes')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build',action='store_true')
    args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    WORK.mkdir(parents=True,exist_ok=True)
    ref=json.loads((BASE/'out/postmarketos-integration-20261016/image-verification.json').read_text())
    assert SOURCE.is_file(), SOURCE
    assert shutil.disk_usage(WORK).free>8*1024**3
    part=next(p for p in ref['image']['partitions'] if p['label']=='pmOS_root')
    with SOURCE.open('rb') as src,ROOT_IMAGE.open('wb') as dst:
        src.seek(part['start']*4096)
        remaining=part['sectors']*4096
        while remaining:
            b=src.read(min(4*1024*1024,remaining));assert b
            dst.write(b);remaining-=len(b)
    assert sha(ROOT_IMAGE)==ref['root_partition_sha256']
    report=[]
    for path in ['/etc/passwd','/etc/fstab','/etc/NetworkManager/system-connections',
                 '/usr/lib/NetworkManager/system-connections','/etc/ssh/sshd_config.d',
                 '/etc/ssh/sshd_config.d/50-postmarketos-ui-policy.conf',
                 '/usr/lib/NetworkManager/conf.d',
                 '/etc/NetworkManager/conf.d',
                 '/usr/share/usb-signaller','/etc/usb-signaller',
                 '/usr/lib/systemd/system/usb-signaller.service',
                 '/usr/lib/systemd/system/unudhcpd@.service']:
        isdir=any(path.endswith(x) for x in ['system-connections','sshd_config.d','conf.d','usb-signaller'])
        cmd=('ls -p ' if isdir else 'cat ')+path
        report.append(path+'\n'+debug(cmd))
    (OUT/'rootfs-inspection.txt').write_text('\n'.join(report))
    print('\n'.join(report))
    print('Original root partition extracted and hashed; no changes applied yet')
    if args.build:
        build(ref)


if __name__=='__main__':
    main()
