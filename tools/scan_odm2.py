import os, glob, re
d = r"H:\workspace\PJA110-Mainline\out\payload_extract\odm"
files = sorted(glob.glob(os.path.join(d,"chunk_*.bin")))
pat = re.compile(rb"[\x20-\x7E]{8,200}")
keys = ["mixer_path","audio_platform","audio_policy","wsa88","wcd938","spkr","Speaker","acdb","ADSP","adsp","sound_trigger","audio_effects","primary","deep_buffer","tasha","kalama","swr"]

hits = {}
for f in files:
    b = open(f,"rb").read()
    for m in pat.finditer(b):
        s = m.group().decode("ascii","ignore")
        low = s.lower()
        for k in keys:
            if k.lower() in low:
                hits.setdefault(k,set()).add(s)
                break

for k in keys:
    v = hits.get(k)
    if v:
        print(f"\n=== {k} ({len(v)} unique) ===")
        for s in sorted(v)[:12]:
            print("   ", s[:160])
