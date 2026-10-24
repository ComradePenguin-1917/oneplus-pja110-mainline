#!/usr/bin/env python3
"""Query patchwork.kernel.org API (via curl) for patches matching a search term."""
import subprocess, json, sys, urllib.parse

CURL = "curl.exe"

def curl_json(url):
    out = subprocess.run([CURL, "-s", "-H", "Accept: application/json", url],
                         capture_output=True)
    txt = out.stdout.decode("utf-8", "replace")
    try:
        return json.loads(txt)
    except Exception:
        return None

def search(q, per_page=100, state=None):
    url = ("https://patchwork.kernel.org/api/patches/?q="
           + urllib.parse.quote(q) + f"&per_page={per_page}&order=-date")
    if state:
        url += "&state=" + urllib.parse.quote(state)
    return curl_json(url) or []

if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "sm8550"
    datefrom = sys.argv[2] if len(sys.argv) > 2 else None
    d = search(q)
    if datefrom:
        d = [p for p in d if (p.get("date") or "") >= datefrom]
    print(f"q={q!r}  count={len(d)}")
    for p in d:
        name = (p.get("name") or "").replace("\n", " ")
        proj = p.get("project", {}).get("link_name", "?")
        print(f"{(p.get('date') or '')[:10]} | {p.get('state'):<16} | {proj:<18} | {p.get('submitter',{}).get('name','')}")
        print(f"    {name}")
        print(f"    {p.get('web_url')}")
