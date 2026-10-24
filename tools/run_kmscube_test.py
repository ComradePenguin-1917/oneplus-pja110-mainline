"""Run unmodified upstream kmscube over existing RAM-only Mesa runtime."""
import hashlib,json,subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/gpu-kms-20261014'
LINEAR='--linear' in sys.argv
SURFACELESS='--surfaceless' in sys.argv
LONG='--long' in sys.argv
SDMA='--sdma' in sys.argv
FIRSTLINE='--firstline' in sys.argv
RECHECK='--weston-recheck' in sys.argv
ATOMIC='--atomic' in sys.argv
if FIRSTLINE:SDMA=True
READBACK='--readback' in sys.argv
if READBACK:
    OUT=ROOT/'out/gpu-scanout-readback-20261014'
if SDMA:
    OUT=ROOT/'out/dpu-sdma-control-20261014/kmscube'
    if FIRSTLINE:OUT=ROOT/'out/dsc-firstline-control-20261014/kmscube'
    OUT.mkdir(exist_ok=True)
if SURFACELESS:
    OUT=OUT/'surfaceless'
    OUT.mkdir(exist_ok=True)
if LINEAR:
    OUT=OUT/'linear'
    OUT.mkdir(exist_ok=True)
if RECHECK:
    OUT=ROOT/'out/weston-kms-diagnosis-20261014'/('atomic' if ATOMIC else 'legacy')
    OUT.mkdir(parents=True,exist_ok=True)
KEYS=ROOT/'out/usb-ncm-20261013/ssh'
SSH=['C:/Windows/System32/OpenSSH/ssh.exe','-F','none','-T','-i',str(KEYS/'client_key_host'),
     '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
     '-o',f'UserKnownHostsFile={KEYS/"known_hosts"}','-o','ConnectTimeout=5','root@169.254.42.1']
def checked(cmd,data=None):
    p=subprocess.run(SSH+[cmd],input=data,capture_output=True,timeout=30)
    p.check_returncode();return p.stdout
before=checked('uname -a; cat /proc/sys/kernel/random/boot_id; dmesg')
(OUT/'before.txt').write_bytes(before)
if SDMA:
    archive=(ROOT/'out/mesa-offscreen-20261014/runtime.tar.gz').read_bytes()
    assert checked('cat > /tmp/mesa-runtime.tar.gz; sha256sum /tmp/mesa-runtime.tar.gz',archive).decode().split()[0]==hashlib.sha256(archive).hexdigest()
    checked('mkdir -p /tmp/mesa-test; tar -xzf /tmp/mesa-runtime.tar.gz -C /tmp/mesa-test; mkdir -p /tmp/mesa-test/run')
    for name,path in [('gpu-probe','out/gpu-port-20261014/gpu-probe'),('fb-pattern','out/display-port-20261013/fb-pattern')]:
        data=(ROOT/path).read_bytes()
        assert checked(f'cat > /tmp/{name}; chmod 700 /tmp/{name}; sha256sum /tmp/{name}',data).decode().split()[0]==hashlib.sha256(data).hexdigest()
    checked('echo 1024 > /sys/class/backlight/ae94000.dsi.0/brightness')
data=(ROOT/('out/gpu-scanout-readback-20261014' if READBACK else 'out/gpu-kms-20261014')/'kmscube-aarch64').read_bytes()
assert checked('cat > /tmp/mesa-test/kmscube; chmod 700 /tmp/mesa-test/kmscube; sha256sum /tmp/mesa-test/kmscube',data).decode().split()[0]==hashlib.sha256(data).hexdigest()
script='''set -e
base=/tmp/mesa-test
export __EGL_VENDOR_LIBRARY_FILENAMES=$base/usr/share/glvnd/egl_vendor.d/50_mesa.json
export LIBGL_DRIVERS_PATH=$base/usr/lib/aarch64-linux-gnu/dri
export GBM_BACKENDS_PATH=$base/usr/lib/aarch64-linux-gnu/gbm
export MESA_LOADER_DRIVER_OVERRIDE=msm
export XDG_RUNTIME_DIR=$base/run
timeout 45 $base/usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 --library-path $base/usr/lib/aarch64-linux-gnu $base/kmscube -D /dev/dri/card0 -N -c 1800
'''
if LINEAR:script=script.replace('-N -c 1800','-N -m 0 -c 1800')
if SURFACELESS:script=script.replace('-N -c 1800','-N -x -c 1800')
if LONG:script=script.replace('timeout 45','timeout 130').replace('-c 1800','-c 7200')
if ATOMIC:script=script.replace('$base/kmscube -D', '$base/kmscube -A -D')
try:
    p=subprocess.run(SSH+[script],capture_output=True,timeout=150 if LONG else 60)
    (OUT/'kmscube-output.txt').write_bytes(p.stdout+p.stderr)
    print((p.stdout+p.stderr).decode(),flush=True)
finally:
    (OUT/'restore-framebuffer.txt').write_bytes(checked('/tmp/fb-pattern --unblank; /tmp/fb-pattern'))
after=checked('cat /proc/sys/kernel/random/boot_id; /tmp/gpu-probe; dmesg')
(OUT/'after.txt').write_bytes(after)
if READBACK and p.returncode==0:
    for name in ('gpu-gl-readback.ppm','gpu-bo-readback.ppm'):
        raw=checked('cat /tmp/'+name)
        assert hashlib.sha256(raw).hexdigest()==checked('sha256sum /tmp/'+name).decode().split()[0]
        (OUT/name).write_bytes(raw)
result=dict(returncode=p.returncode,upstream_commit='f60e50e887d3c49e91ac9b06d8199b36152632fa',
            binary_sha256=hashlib.sha256(data).hexdigest(),partitions_written=False,
            visual_confirmation_pending=True)
result['forced_linear_modifier']=LINEAR
result['surfaceless']=SURFACELESS
result['atomic_kms']=ATOMIC
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
assert p.returncode in (0,124)
