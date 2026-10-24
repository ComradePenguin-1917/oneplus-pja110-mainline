#!/usr/bin/env python3
"""Query lore.kernel.org Atom search feeds and print compact title/link/date lists."""
import urllib.request, urllib.parse, re, sys, time
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"

def fetch(listname, query, limit=40):
    url = (f"https://lore.kernel.org/{listname}/?q="
           + urllib.parse.quote(query) + "&x=A")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) research-client",
        "Accept": "application/atom+xml, application/xml, text/xml",
    })
    try:
        data = urllib.request.urlopen(req, timeout=60).read()
    except Exception as e:
        print(f"!! {listname} q={query!r}: {e}")
        return
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"!! parse error {listname} q={query!r}: {e}")
        return
    entries = root.findall(ATOM + "entry")
    print(f"### [{listname}] q={query!r}  -> {len(entries)} results")
    seen = set()
    for e in entries[:limit]:
        t = e.findtext(ATOM + "title") or ""
        t = re.sub(r"\s+", " ", t).strip()
        d = (e.findtext(ATOM + "updated") or "")[:10]
        link = e.find(ATOM + "link")
        href = link.get("href") if link is not None else ""
        a = e.find(ATOM + "author")
        author = a.findtext(ATOM + "name") if a is not None else ""
        key = (t, d)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {d} | {author} | {t}")
        print(f"      {href}")
    print()

if __name__ == "__main__":
    queries = [
        ("linux-arm-msm", 'sm8550 dts qcom'),
        ("linux-arm-msm", 'sm8550 bindings'),
        ("linux-devicetree", 'sm8550'),
        ("dri-devel", 'sm8550 adreno'),
        ("linux-arm-msm", 'sm8550 ufs'),
        ("linux-arm-msm", 'sm8550 pcie'),
    ]
    for lst, q in queries:
        fetch(lst, q)
        time.sleep(1)
