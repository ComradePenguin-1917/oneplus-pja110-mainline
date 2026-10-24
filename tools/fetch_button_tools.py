"""Fetch unmodified upstream evtest for input diagnosis, recording provenance."""
import hashlib
import json
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/buttons-20261013/upstream'
OUT.mkdir(exist_ok=True)
url='https://gitlab.freedesktop.org/libevdev/evtest/-/raw/master/evtest.c'
req=urllib.request.Request(url,headers={'User-Agent':'PJA110-input-bringup'})
with urllib.request.urlopen(req,timeout=30) as response:data=response.read()
blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
assert blob=='0cb59b45457873bed298a7ced0e1c9912899702c','Upstream file drifted; inspect before use'
(OUT/'evtest.c').write_bytes(data)
(OUT/'manifest.json').write_text(json.dumps({'source':url,'git_blob':blob,
    'sha256':hashlib.sha256(data).hexdigest(),'source_unmodified':True},indent=2)+'\n')
print('Fetched unmodified upstream evtest; Git blob verified')
