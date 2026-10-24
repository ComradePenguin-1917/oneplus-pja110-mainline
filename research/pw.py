#!/usr/bin/env python3
"""Query patchwork.kernel.org API for patches matching a search term."""
import urllib.request, urllib.parse, json, sys, time

HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36",
        "Accept": "application/json"}

def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def search(q, states=None, projects=None, per_page=100):
    url = ("https://patchwork.kernel.org/api/patches/?q="
           + urllib.parse.quote(q) + f"&per_page={per_page}&order=-date")
    if states:
        for s in states:
            url += "&state=" + urllib.parse.quote(s)
    try:
        data = get(url)
    except Exception as e:
        print(f"!! {q}: {e}")
        return []
    return data

if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "sm8550"
    states = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    d = search(q, states)
    print(f"q={q!r} states={states} count={len(d)}")
    for p in d:
        name = (p.get("name") or "").replace("\n", " ")
        print(f"{p.get('date','')[:10]} | {p.get('state')} | {p.get('submitter',{}).get('name','')} | {name}")
        print(f"    {p.get('web_url')}")
