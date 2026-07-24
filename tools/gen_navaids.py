#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全国 nav aids 生成 (NAVAIDS)
=============================
AIP Japan ENR 4.1 (無線航法施設-エンルート) から VOR/DME/TACAN/NDB を抽出し、
index.html の /*NAVAIDS_GEN_START*/ ... /*NAVAIDS_GEN_END*/ 区間へ埋め込む。

使い方:
  python3 tools/gen_navaids.py            # tools/navaids.gen.js を出力
  python3 tools/gen_navaids.py --splice   # index.html へ埋め込み

データソース(AIRAC 2026-07-09):
  ~/Downloads/1_AIP (PDF)/<日付>/ENR_<日付>.pdf の ENR 4.1
AIRAC更新時: 新PDFで ENR 4.1 を pdftotext -layout し、下の PDF/範囲を差し替えて再実行。
同一IDのVOR+DMEは VOR/DME に統合する。
"""
import re, json, sys, os, subprocess, glob

def find_pdf():
    base=os.path.expanduser('~/Downloads/1_AIP (PDF)')
    cands=sorted(glob.glob(base+'/*/ENR_*.pdf'))
    return cands[-1] if cands else None

def dms(v):
    # 度分秒は小数点が無い表記(例: 352644N)もあるため \d+(\.\d+)? で両対応する
    ip=v.split('.')[0]
    if len(ip)==6: d,rest=float(v[:2]),v[2:]
    else: d,rest=float(v[:3]),v[3:]
    return d+float(rest[:2])/60+float(rest[2:])/3600

def parse(lines):
    raw=[]
    LAT_RE=re.compile(r'(\d{6}(?:\.\d+)?)N')
    LNG_RE=re.compile(r'(\d{7}(?:\.\d+)?)E')
    for i,ln in enumerate(lines):
        mlat=LAT_RE.search(ln); mtype=re.search(r'\b(VORTAC|VOR/DME|TACAN|VOR|DME|NDB)\b',ln)
        if not(mlat and mtype):continue
        typ=mtype.group(1)
        mid=re.search(r'\b([A-Z]{2,3})\b\s+(\d{3}\.\d+MHz|\d{3,4}MHz|\d{3}\.\d+kHz)',ln)
        idc=mid.group(1) if mid else ''; freq=mid.group(2) if mid else ''
        lat=dms(mlat.group(1)); name=''
        for k in range(i-1,max(0,i-5),-1):
            t=lines[k].strip()
            m=re.match(r'^([A-Z][A-Z][A-Z \-]*?[A-Z])(?:\s{2,}|\s*$)',t)
            if m and 'MHZ' not in t and not re.match(r'^(VOR|DME|TACAN|NDB|CH|HR|STN|ID)\b',t):
                name=m.group(1).strip();break
        lng=None;ch=''
        for k in range(i,min(len(lines),i+3)):
            ml=LNG_RE.search(lines[k])
            if ml and lng is None:lng=dms(ml.group(1))
            mc=re.search(r'\(CH-?([\dA-Z]+)\)',lines[k])
            if mc and not ch:ch=mc.group(1)
        if lng:raw.append(dict(n=name.title(),t=typ,id=idc,f=freq,ch=ch,lat=round(lat,5),lng=round(lng,5)))
    byid={}
    for a in raw:byid.setdefault(a['id'],[]).append(a)
    out=[]
    for idc,g in byid.items():
        types={x['t'] for x in g}
        if 'VOR' in types and 'DME' in types:
            v=[x for x in g if x['t']=='VOR'][0]; d=[x for x in g if x['t']=='DME'][0]
            out.append(dict(n=v['n']or d['n'],t='VOR/DME',id=idc,f=v['f']+'/'+d['f'],ch=d['ch'],lat=v['lat'],lng=v['lng']))
            out+=[x for x in g if x['t'] not in('VOR','DME')]
        else:
            seen=set()
            for x in g:
                k=(x['t'],round(x['lat'],3))
                if k in seen:continue
                seen.add(k);out.append(x)
    out.sort(key=lambda a:a['lat'])
    return out

def main():
    pdf=find_pdf()
    if not pdf: print('AIP PDF not found under ~/Downloads',file=sys.stderr); sys.exit(1)
    txt=subprocess.run(['pdftotext','-layout',pdf,'-'],capture_output=True,text=True).stdout
    lines=txt.split('\n')
    # ENR 4.1 の本文範囲(見出し行〜ENR 4.2 見出し)を切り出し
    s=[i for i,l in enumerate(lines) if re.match(r'ENR 4\.1 ',l.strip())]
    e=[i for i,l in enumerate(lines) if re.match(r'ENR 4\.2 ',l.strip())]
    seg=lines[s[-1]:e[-1]] if s and e else lines
    na=parse(seg)
    js='/* 自動生成: tools/gen_navaids.py — AIP Japan ENR 4.1 */\nconst NAVAIDS='+json.dumps(na,ensure_ascii=False,separators=(',',':'))+';'
    here=os.path.dirname(os.path.abspath(__file__))
    open(os.path.join(here,'navaids.gen.js'),'w').write(js+'\n')
    print(f'{len(na)} nav aids → tools/navaids.gen.js')
    if '--splice' in sys.argv:
        idx=os.path.join(here,'..','index.html'); h=open(idx).read()
        a,b='/*NAVAIDS_GEN_START*/','/*NAVAIDS_GEN_END*/'
        i,j=h.index(a),h.index(b)
        h=h[:i+len(a)]+'\n'+js+'\n'+h[j:]
        open(idx,'w').write(h); print('spliced into index.html')

if __name__=='__main__': main()
