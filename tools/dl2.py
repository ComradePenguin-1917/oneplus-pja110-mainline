import lzma, bz2, os
man = open(r"H:\workspace\PJA110-Mainline\out\payload_manifest.bin","rb").read()
def rv(b,i):
    r=0;s=0
    while True:
        x=b[i];i+=1;r|=(x&0x7f)<<s
        if not(x&0x80):break
        s+=7
    return r,i
def fields(b):
    i=0;out=[]
    while i<len(b):
        try: k,i=rv(b,i)
        except: break
        f=k>>3;w=k&7
        if w==0: v,i=rv(b,i);out.append((f,w,v))
        elif w==2:
            ln,i=rv(b,i);out.append((f,w,b[i:i+ln]));i+=ln
        elif w==5: out.append((f,w,b[i:i+4]));i+=4
        elif w==1: out.append((f,w,b[i:i+8]));i+=8
        else: break
    return out

payload = r"H:\workspace\PJA110-Mainline\PJA110 线刷包-701\payload.bin"
DATA_START = 279896
BLOCK = 4096

for f,w,v in fields(man):
    if f==13 and w==2:
        name=None; ops=[]
        for f2,w2,v2 in fields(v):
            if f2==1 and w2==2: name=v2.decode('utf-8','ignore')
            elif f2==8 and w2==2:
                d={'type':None,'off':None,'len':None,'exts':[]}
                for f3,w3,v3 in fields(v2):
                    if f3==1 and w3==0: d['type']=v3
                    elif f3==2 and w3==0: d['off']=v3
                    elif f3==3 and w3==0: d['len']=v3
                    elif f3==6 and w3==2:
                        sb=nb=None
                        for f4,w4,v4 in fields(v3):
                            if f4==1: sb=v4
                            elif f4==2: nb=v4
                        d['exts'].append((sb,nb))
                ops.append(d)
        if name=="vendor_dlkm":
            maxblk=0
            for o in ops:
                for sb,nb in o['exts']:
                    if sb is not None and nb: maxblk=max(maxblk, sb+nb)
            print("vendor_dlkm: %d blocks -> %.1f MB" % (maxblk, maxblk*BLOCK/1024/1024))
            img=bytearray(maxblk*BLOCK)
            fh=open(payload,"rb")
            for o in ops:
                if o['type'] not in (0,1,8) or not o['exts'] or o['off'] is None: continue
                fh.seek(DATA_START+o['off']); data=fh.read(o['len'])
                if o['type']==8:
                    try: data=lzma.decompress(data)
                    except: continue
                elif o['type']==1:
                    try: data=bz2.decompress(data)
                    except: continue
                pos=0
                for sb,nb in o['exts']:
                    if sb is None or not nb: continue
                    n=nb*BLOCK; chunk=data[pos:pos+n]; pos+=n
                    img[sb*BLOCK:sb*BLOCK+len(chunk)]=chunk
            fh.close()
            dst=r"H:\workspace\PJA110-Mainline\out\payload_extract\vendor_dlkm.img"
            open(dst,"wb").write(img)
            print("wrote", dst)
            break
