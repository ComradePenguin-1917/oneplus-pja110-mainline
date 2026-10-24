import re, glob, os, collections

d = "/lib/firmware/qcom/sm8550/xigua"
files = sorted(glob.glob(os.path.join(d, "adsp.b*")))
print(f"segments: {len(files)}")

pat = re.compile(rb"[\x20-\x7E]{5,80}")
keys = [b"APM", b"apm", b"AudioReach", b"audioreach", b"SPF", b"spf", b"subgraph",
        b"container", b"MODULE", b"module_iid", b"wsa", b"wcd", b"tplg", b"topology"]
hits = collections.defaultdict(set)
total = 0
for f in files:
    b = open(f, "rb").read()
    total += len(b)
    for m in pat.finditer(b):
        s = m.group()
        for k in keys:
            if k in s:
                hits[k].add(s.decode("ascii","ignore"))
                break

print(f"scanned {total/1024/1024:.1f} MB")
for k in keys:
    v = hits.get(k.decode())
    print(f"  {k.decode():12s}: {len(v) if v else 0}")
