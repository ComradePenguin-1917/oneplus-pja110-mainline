from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

out=Path(__file__).resolve().parents[1]/'out/phoc-commit-20261015/source'
out.mkdir(exist_ok=True)
base='https://gitlab.gnome.org/Infrastructure/Mirrors/lorry-mirrors/gitlab_freedesktop_org/wlroots/wlroots/-/raw/0.20.2/'
urls={
    'wlroots-drm.h':base+'include/backend/drm/drm.h',
    'wlroots-atomic.c':base+'backend/drm/atomic.c',
    'wlroots-drm.c':base+'backend/drm/drm.c',
    'phoc-output.c':'https://gitlab.gnome.org/World/Phosh/phoc/-/raw/v0.57.0/src/output.c',
    'wlroots-output-cursor.c':base+'types/output/cursor.c',
    'phoc-server.c':'https://gitlab.gnome.org/World/Phosh/phoc/-/raw/v0.57.0/src/server.c',
    'phoc-main.c':'https://gitlab.gnome.org/World/Phosh/phoc/-/raw/v0.57.0/src/main.c',
}
def fetch(item):
    name,url=item
    try:
        data=urlopen(url,timeout=25).read()
        if data.startswith(b'<!DOCTYPE') or data.startswith(b'<html'):
            raise ValueError('HTML response instead of source')
        (out/name).write_bytes(data)
        return name,len(data)
    except Exception as e:
        return name,str(e)
with ThreadPoolExecutor(max_workers=4) as pool:
    for result in pool.map(fetch,urls.items()):
        print(result,flush=True)
