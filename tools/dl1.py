import json
p = json.load(open(r"H:\workspace\PJA110-Mainline\out\payload_parts.json"))
TYPE={0:"REPLACE",1:"BZ",2:"MOVE",3:"BSDIFF",4:"SRC_COPY",5:"SRC_BSDIFF",6:"ZERO",7:"DISCARD",8:"XZ"}
for name in ["vendor_dlkm","system_dlkm"]:
    ops = p.get(name, [])
    from collections import Counter
    print(f"{name}: {len(ops)} ops, types={dict(Counter(TYPE.get(o[0],'?') for o in ops))}")
    reps=[o for o in ops if o[0] in (0,1,8) and o[1] is not None]
    tot=sum(o[2] for o in reps)
    print(f"   extractable: {len(reps)} ops, {tot/1024/1024:.1f} MB")
