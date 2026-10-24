#!/usr/bin/env python3
"""Collect patchwork results across pages (via curl) and summarise by series."""
import subprocess, json, sys, urllib.parse, re, collections

def curl_json(url):
    out = subprocess.run(["curl.exe", "-s", "-H", "Accept: application/json", url],
                         capture_output=True)
    try:
        return json.loads(out.stdout.decode("utf-8", "replace"))
    except Exception:
        return None

def collect(q, pages=4, per_page=100):
    rows = []
    for pg in range(1, pages + 1):
        url = ("https://patchwork.kernel.org/api/patches/?q=" + urllib.parse.quote(q)
               + f"&per_page={per_page}&page={pg}&order=-date")
        d = curl_json(url)
        if not d:
            break
        rows.extend(d)
        if len(d) < per_page:
            break
    return rows

q = sys.argv[1] if len(sys.argv) > 1 else "sm8550"
minlen = int(sys.argv[2]) if len(sys.argv) > 2 else 0
rows = collect(q)

# dedupe: same patch name appearing in multiple projects -> keep one
seen = set()
uniq = []
for p in rows:
    key = (p.get("name"), p.get("date","")[:10], p.get("submitter",{}).get("id"))
    if key in seen:
        continue
    seen.add(key)
    uniq.append(p)

print(f"total raw={len(rows)} unique={len(uniq)}")
print("=" * 100)

# group by series: strip the [vN,M/T] prefix
series = collections.defaultdict(list)
for p in uniq:
    n = (p.get("name") or "").replace("\n", " ")
    proj = p.get("project", {}).get("link_name", "?")
    series[(proj, p.get("date","")[:10])].append(p)

for (proj, date), ps in sorted(series.items(), key=lambda kv: kv[0][1], reverse=True):
    ps.sort(key=lambda p: p.get("name",""))
    for p in ps[:1]:
        print(f"{date} | {proj:<16} | {p.get('state'):<18} | {p.get('submitter',{}).get('name','')}")
        print(f"    {(p.get('name') or '').strip()}")
        print(f"    {p.get('web_url')}")
