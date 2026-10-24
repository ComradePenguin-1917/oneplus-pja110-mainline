"""Offline slot-A charging candidate from known-working native containers."""
from pathlib import Path
import gzip, hashlib, json, struct, subprocess
from bootimg import BootImage
from build_init_marker_test import lz4, parse_cpio
from fdt import FDT, scan_for_fdt
from package_native_pmos import avb_offset, align
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"out/native-install-20261017"
SRC=BASE/"rootfs-integrated"
OUT=BASE/"charger-startup"
OUT.mkdir(exist_ok=True)
sha=lambda b: hashlib.sha256(b).hexdigest()
m=json.loads((SRC/"manifest.json").read_text())
old=ROOT/"out/native-install-20261016/native-images"
kernel=(SRC/"vmlinuz").read_bytes()
assert kernel[56:60]==b"ARM\x64"
boot=BootImage.parse(str(old/"boot_a.img"))
boot.kernel=kernel
cmdline="root=UUID="+m["root_uuid"]+" rootwait rw loglevel=4"
original=(old/"boot_a.img").read_bytes()
offset=avb_offset(original)
prefix=boot.pack(cmdline=cmdline)
assert len(prefix)<offset
(OUT/"boot_a.img").write_bytes(prefix+bytes(offset-len(prefix))+original[offset:])
assert BootImage.parse(str(OUT/"boot_a.img")).kernel==kernel
vendor=(ROOT/"out/battery-bringup-20261016/vendor_boot_a-battery.img").read_bytes()
record=json.loads((ROOT/"out/battery-bringup-20261016/candidate.json").read_text())
assert sha(vendor)==record["candidate_sha256"]
new=bytearray(vendor)
rdsize=struct.unpack_from("<I",vendor,24)[0]
hsize,dsize=struct.unpack_from("<II",vendor,2096)
rdoff=align(hsize);dtboff=align(rdoff+rdsize)
archive=gzip.decompress((SRC/"initramfs").read_bytes())
assert any(n.removeprefix("./")=="init" for _,n,_ in parse_cpio(archive))
compressed=lz4(["-z","-l","-12","-c"],archive)
assert len(compressed)<=rdsize
assert lz4(["-d","-l","-c"],compressed)==archive
new[rdoff:rdoff+rdsize]=compressed+bytes(rdsize-len(compressed))
changes=[]
for off,size,tree in scan_for_fdt(vendor[dtboff:dtboff+dsize]):
    nodes=tree.nodes()
    if nodes["/"].get("model")!=b"OnePlus Ace 2 Pro\0":continue
    candidates=[p for p,v in nodes.items() if b"qcom,sm8550-adsp-pas" in v.get("compatible",b"")]
    assert len(candidates)==1,candidates
    node=candidates[0]
    path=OUT/"adsp-enabled.dtb"
    path.write_bytes(vendor[dtboff+off:dtboff+off+size])
    for prop,values in [("status",["okay"]),("firmware-name",["qcom/sm8550/xigua/adsp.mdt","qcom/sm8550/xigua/adsp_dtb.mdt"])]:
        wslpath="/mnt/h/"+path.relative_to(Path("H:/")).as_posix()
        subprocess.run(["wsl.exe","-d","Ubuntu-22.04","--","fdtput","-t","s",wslpath,node,prop,*values],check=True)
    data=path.read_bytes();updated=FDT(data).nodes()
    diff={(p,k) for p in nodes.keys()|updated.keys() for k in nodes.get(p,{}).keys()|updated.get(p,{}).keys() if nodes.get(p,{}).get(k)!=updated.get(p,{}).get(k)}
    assert diff=={(node,"status"),(node,"firmware-name")},diff
    assert len(data)<=size
    padded=bytearray(data.ljust(size,b"\0"));struct.pack_into(">I",padded,4,size)
    assert FDT(padded).nodes()==updated
    new[dtboff+off:dtboff+off+size]=padded
    changes.append(node)
assert len(changes)==1
assert len(new)==len(vendor)
assert new[dtboff+dsize:]==vendor[dtboff+dsize:]
(OUT/"vendor_boot_a.img").write_bytes(new)
for name in ["init_boot_a.img","dtbo_a.img"]:
    (OUT/name).write_bytes((old/name).read_bytes())
files={n:{"bytes":(OUT/n).stat().st_size,"sha256":sha((OUT/n).read_bytes())} for n in ["boot_a.img","vendor_boot_a.img","init_boot_a.img","dtbo_a.img"]}
(OUT/"manifest.json").write_text(json.dumps({"root_uuid":m["root_uuid"],"cmdline":cmdline,"adsp_node":changes[0],"firmware_format":"split MDT","files":files,"offline_checks_passed":True,"phone_written":False},indent=2)+"\n")
print("PASS: current kernel/initramfs, matching root UUID, ADSP split MDT paths; only ADSP properties changed in working battery DTB")
