import os,sys,io,re,math,time,json,csv,urllib.parse,urllib.request,urllib.error
from PIL import Image
import fitz
I=int(os.environ.get("I","0"));N=int(os.environ.get("N","1"));L=os.environ.get("L","data/l.csv")
W=os.environ.get("W","").rstrip("/")
CL=3000;UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64)";TO=120
def lg(m):print(f"[{I}/{N}]{time.strftime('%H:%M:%S')} {m}",flush=True)
def gt(u,tr=8,to=TO):
    for i in range(tr):
        t=(f"{W}/fetch?url={urllib.parse.quote(u,safe='')}" if(W and i%2==0) else u)
        try:
            q=urllib.request.Request(t,headers={"User-Agent":UA})
            with urllib.request.urlopen(q,timeout=to) as rs:
                b=rs.read()
                if b and len(b)>300:return b
        except urllib.error.HTTPError as e:
            if e.code in (403,429):time.sleep(min(60,8*(i+1)));continue
            time.sleep(2)
        except:time.sleep(2)
    return None
def gj(u):
    b=gt(u,tr=4);return json.loads(b) if b else None
def pg(s,w,h):
    co=math.ceil(w/CL);ro=math.ceil(h/CL);cv=Image.new("RGB",(w,h),(255,255,255));ok=True
    for cy in range(ro):
        for cx in range(co):
            x,y=cx*CL,cy*CL;ww,hh=min(CL,w-x),min(CL,h-y)
            b=gt(f"{s}/{x},{y},{ww},{hh}/full/0/default.jpg")
            if not b:ok=False;continue
            try:cv.paste(Image.open(io.BytesIO(b)).convert("RGB"),(x,y))
            except:ok=False
    return cv,ok
def do(it):
    iid=str(it.get("id") or "").strip();mu=(it.get("manifest") or "").strip()
    if not mu or not iid:return None
    nm=re.sub(r'[^0-9A-Za-z._-]+','_',iid)[:60];op=f"pdf_out/{nm}.pdf"
    if os.path.exists(op):lg(f"skip {nm}");return{"id":iid,"ok":True,"skip":True}
    mn=gj(mu)
    if not mn:lg(f"manifest fail {nm}");return{"id":iid,"ok":False}
    try:cvs=mn["sequences"][0]["canvases"]
    except:cvs=[]
    if not cvs:lg(f"no canvas {nm}");return{"id":iid,"ok":False}
    doc=fitz.open();k=0;fl=0
    for c in cvs:
        w,h=int(c.get("width",0)),int(c.get("height",0))
        try:rs=c["images"][0]["resource"];sv=rs.get("service") or {}
        except:fl+=1;continue
        sd=(sv.get("@id") or sv.get("id") or "").rstrip("/")
        if not(sd and w and h):fl+=1;continue
        im,ok=pg(sd,w,h)
        if not ok:fl+=1;continue
        jb=io.BytesIO();im.save(jb,"JPEG",quality=92)
        try:
            fi=fitz.open(stream=jb.getvalue(),filetype="jpg");doc.insert_pdf(fitz.open("pdf",fi.convert_to_pdf()));fi.close();k+=1
        except:fl+=1
    if k==0 or fl>0:lg(f"incomplete {nm} {k}/{fl}");doc.close();return{"id":iid,"ok":False,"kept":k,"failed":fl}
    os.makedirs("pdf_out",exist_ok=True);doc.save(op);doc.close();lg(f"ok {nm} {k}p")
    return{"id":iid,"ok":True,"kept":k}
def main():
    rows=[]
    with open(L,encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):rows.append(r)
    mine=[r for i,r in enumerate(rows) if i%N==I];lg(f"shard {len(mine)} of {len(rows)}")
    out=[]
    for it in mine:
        try:
            r=do(it)
            if r:out.append(r)
        except Exception as e:lg(f"err {e}")
    lg(f"done {sum(1 for r in out if r.get('ok'))}/{len(mine)}")
    os.makedirs("pdf_out",exist_ok=True);open("pdf_out/_r.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False))
if __name__=="__main__":main()
