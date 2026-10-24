"""Build offline-only slot-A native pmOS candidates from verified local inputs.

No phone access or flashing. Retained AVB metadata is not a valid signature of
the modified contents: this candidate relies on the existing unlocked device.
"""
import gzip
import hashlib
import json
from pathlib import Path
import struct

from bootimg import BootImage
from build_init_marker_test import lz4, make_entry, parse_cpio
from fdt import FDT

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'out/native-install-20261016'
OUT = BASE/'native-images'
DISTRO = ROOT/'out/postmarketos-integration-20261016'
BACKUP = BASE/'backup'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(n):
    return (n+4095)//4096*4096


def avb_offset(data):
    magic, major, minor, original_size, offset, size, _ = struct.unpack('>4sIIQQQ28s', data[-64:])
    assert magic==b'AVBf' and data[offset:offset+4]==b'AVB0'
    assert 0<original_size<=offset and offset+size<=len(data)-64
    return offset


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    # Prevent a previous successful result from surviving a failed rebuild.
    (OUT/'manifest.json').unlink(missing_ok=True)
    expected = json.loads((BASE/'backup-verification.json').read_text())
    artifacts = json.loads((DISTRO/'artifacts.json').read_text())['files']
    inputs = {}

    def backup(name):
        data=(BACKUP/(name+'.img')).read_bytes()
        assert len(data)==expected[name]['bytes'] and sha(data)==expected[name]['sha256'], name
        inputs[name]=sha(data)
        return data

    def distro(name):
        data=(DISTRO/name).read_bytes()
        assert len(data)==artifacts[name]['bytes'] and sha(data)==artifacts[name]['sha256'], name
        inputs[name]=sha(data)
        return data

    kernel=distro('vmlinuz')
    assert kernel[56:60]==b'ARM\x64'
    start=kernel.index(b'IKCFG_ST')
    end=kernel.index(b'IKCFG_ED',start+8)
    config=gzip.decompress(kernel[start+8:end]).decode()
    assert 'CONFIG_INITRAMFS_SOURCE=""\n' in config
    assert 'CONFIG_CMDLINE_FORCE=y' not in config
    for key in ['RD_LZ4','SCSI_UFS_QCOM','EXT4_FS','BLK_DEV_LOOP','EFI_PARTITION']:
        assert f'CONFIG_{key}=y\n' in config, key
    archive=gzip.decompress(distro('initramfs'))
    entries=parse_cpio(archive)
    content={n.removeprefix('./'):(f,d) for f,n,d in entries}
    assert content['init'][1].startswith(b'#!/bin/busybox ash')
    assert 'init_2nd.sh' in content
    assert b'mount_subpartitions' in content['init_functions.sh'][1]
    assert not any(n.endswith('client_key_host') for n in content)
    rd=lz4(['-z','-l','-12','-c'],archive)
    assert lz4(['-d','-l','-c'],rd)==archive

    # Use the tested vendor DTB container and preserve every offset. The one
    # platform fragment remains the same size, with zero padding after our LZ4
    # stream. Linux accepts zero padding between concatenated initramfs streams;
    # the QEMU check exercises exactly these bytes plus the generic fragment.
    vendor=backup('vendor_boot_b')
    assert vendor[:8]==b'VNDRBOOT'
    version,page=struct.unpack_from('<II',vendor,8)
    assert version==4 and page==4096
    rdsize=struct.unpack_from('<I',vendor,24)[0]
    hsize,dsize=struct.unpack_from('<II',vendor,2096)
    rdoff=align(hsize)
    dtboff=align(rdoff+rdsize)
    tableoff=align(dtboff+dsize)
    tsize,count,esize,bcsize=struct.unpack_from('<IIII',vendor,2112)
    assert count==1 and esize==108 and tsize==108
    assert struct.unpack_from('<III',vendor,tableoff)==(rdsize,0,1)
    assert len(rd)<=rdsize and dtboff+dsize<avb_offset(vendor)
    reference=(ROOT/'postmarketos/device/testing/device-oneplus-xigua/verified-vendor.dtb').read_bytes()
    dtb=vendor[dtboff:dtboff+len(reference)]
    assert dtb==reference
    assert b'oneplus,xigua' in FDT(dtb).nodes()['/']['compatible']
    native_vendor=bytearray(vendor)
    native_vendor[rdoff:rdoff+rdsize]=rd+bytes(rdsize-len(rd))
    assert native_vendor[:rdoff]==vendor[:rdoff]
    assert native_vendor[rdoff+rdsize:]==vendor[rdoff+rdsize:]

    # Generic ramdisk is an empty newc archive. It supplies no /init or Android
    # configuration after the platform ramdisk has populated the initial root.
    generic=backup('init_boot_a')
    assert generic[:8]==b'ANDROID!' and struct.unpack_from('<I',generic,40)[0]==4
    assert struct.unpack_from('<I',generic,8)[0]==0
    old_size=struct.unpack_from('<I',generic,12)[0]
    fields=[0,0,0,0,1,0,0,0,0,0,0,0,0]
    empty=make_entry(fields,'TRAILER!!!',b'')
    empty_lz4=lz4(['-z','-l','-12','-c'],empty)
    assert parse_cpio(lz4(['-d','-l','-c'],empty_lz4))[0][1]=='TRAILER!!!'
    old_end=4096+align(old_size)
    assert old_end<=avb_offset(generic) and len(empty_lz4)<old_size
    native_generic=bytearray(generic)
    struct.pack_into('<I',native_generic,12,len(empty_lz4))
    native_generic[4096:old_end]=empty_lz4+bytes(old_end-4096-len(empty_lz4))
    assert native_generic[old_end:]==generic[old_end:]

    stockboot=backup('boot_a')
    base=BootImage.parse(str(BACKUP/'boot_a.img'))
    boot=BootImage()
    boot.header_version=base.header_version
    boot.os_version=base.os_version
    boot.kernel=kernel
    verify=json.loads((DISTRO/'image-verification.json').read_text())
    root_uuid=verify['image']['root_uuid']
    cmdline=f'root=UUID={root_uuid} rootwait rw loglevel=4'
    prefix=boot.pack(cmdline=cmdline)
    offset=avb_offset(stockboot)
    assert len(prefix)<offset
    native_boot=bytearray(stockboot)
    # Remove the previous kernel payload without touching the AVB region.
    native_boot[:offset]=prefix+bytes(offset-len(prefix))
    assert native_boot[offset:]==stockboot[offset:]

    files={'boot_a.img':bytes(native_boot),
           'init_boot_a.img':bytes(native_generic),
           'vendor_boot_a.img':bytes(native_vendor),
           'dtbo_a.img':backup('dtbo_b'),
           'extracted-kernel':kernel,
           'combined-initrd.lz4':bytes(native_vendor[rdoff:rdoff+rdsize])+empty_lz4}
    for name,data in files.items():
        (OUT/name).write_bytes(data)
    unpacked=BootImage.parse(str(OUT/'boot_a.img'))
    assert unpacked.kernel==kernel and unpacked.ramdisk==b''
    assert unpacked.cmdline==cmdline.encode() and unpacked.header_version==4
    disk_vendor=(OUT/'vendor_boot_a.img').read_bytes()
    disk_generic=(OUT/'init_boot_a.img').read_bytes()
    generic_size=struct.unpack_from('<I',disk_generic,12)[0]
    combined=disk_vendor[rdoff:rdoff+rdsize]+disk_generic[4096:4096+generic_size]
    assert combined==(OUT/'combined-initrd.lz4').read_bytes()
    assert unpacked.kernel==(OUT/'extracted-kernel').read_bytes()
    for name in ['boot_a','init_boot_a','vendor_boot_a','dtbo_a']:
        assert len(files[name+'.img'])==expected[name]['bytes']
    result={'target_slot':'a','rescue_slot':'b', 'kernel_release':'6.14.0-oneplus-xigua',
            'root_uuid':root_uuid, 'cmdline':cmdline,
            'delivery':'complete unchanged distro initramfs in padded vendor platform fragment; empty generic archive',
            'inputs_sha256':inputs, 'vendor_fragment_bytes':rdsize,
            'compressed_distro_ramdisk_bytes':len(rd),
            'vendor_dtb_and_offsets_unchanged':True,
            'no_debug_initramfs_embedded_in_kernel':True,
            'avb_metadata_retained_but_modified_payload_not_resigned':True,
            'requires_unlocked_bootloader':True,
            'local_pack_unpack_checks_passed':True, 'qemu_combined_payload_tested':False,
            'native_phone_boot_verified':False,'phone_partitions_written':False,
            'files':{n:{'bytes':len(d),'sha256':sha(d)} for n,d in files.items()}}
    (OUT/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUT/'SHA256SUMS').write_text(''.join(f'{sha(d)}  {n}\n' for n,d in files.items()))
    print('PASS: slot-A candidate generated and unpacked; no phone access')
    print('Distro LZ4 bytes:',len(rd),'vendor fragment capacity:',rdsize)
    print('QEMU and native phone boot not yet verified')


if __name__=='__main__':
    build()
