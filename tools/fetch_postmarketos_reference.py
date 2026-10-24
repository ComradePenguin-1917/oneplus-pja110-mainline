"""Fetch device-package conventions without installing pmbootstrap."""
import urllib.request,json,hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'out/postmarketos-reference-20261014';out.mkdir(exist_ok=True)
api='https://gitlab.postmarketos.org/api/v4/projects/226'
commit=json.load(urllib.request.urlopen(api+'/repository/commits/main',timeout=25))['id']
base=f'https://gitlab.postmarketos.org/postmarketOS/pmaports/-/raw/{commit}/'
paths=['device/testing/device-oneplus-aston/APKBUILD','device/testing/device-oneplus-aston/deviceinfo',
'device/community/device-oneplus-aston/APKBUILD','device/community/device-oneplus-aston/deviceinfo',
'device/testing/device-oneplus-xigua/APKBUILD','device/testing/device-oneplus-xigua/deviceinfo',
'device/community/device-oneplus-enchilada/APKBUILD','device/community/device-oneplus-enchilada/deviceinfo',
'device/main/device-fairphone-fp5/APKBUILD','device/main/device-fairphone-fp5/deviceinfo',
'main/devicepkg-dev/devicepkg_build.sh','main/devicepkg-dev/devicepkg_package.sh',
'main/devicepkg-dev/APKBUILD','main/postmarketos-mkinitfs/APKBUILD']
paths+=['README.md','device/testing/device-oneplus-salami/APKBUILD','device/testing/device-oneplus-salami/deviceinfo',
'device/community/device-oneplus-enchilada/APKBUILD','device/community/device-oneplus-enchilada/deviceinfo']
def fetch(path):
 url=base+path
 try:
  data=urllib.request.urlopen(url,timeout=25).read()
  dest=out/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
  return dict(path=path,url=url,sha256=hashlib.sha256(data).hexdigest(),status='ok')
 except Exception as e:return dict(path=path,url=url,status=str(e))
with ThreadPoolExecutor(max_workers=6) as pool:records=list(pool.map(fetch,paths))
(out/'manifest.json').write_text(json.dumps({'commit':commit,'files':records},indent=2)+'\n')
for r in records:print(r['status'],r['path'])
