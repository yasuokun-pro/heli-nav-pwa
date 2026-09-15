#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飛行場の航法援助施設 生成 (adnav.json)
======================================
出典: AIP Japan 各飛行場 **AD 2.19 RADIO NAVIGATION AND LANDING AIDS**。

ENR 4.1(経路用 navaid・129局)に**載らない飛行場の施設**を拾う。
ENR 4.3 の FIX の評定欄("178°/5.4NM TNT")に出てくる navaid の 210 種のうち
81 種は ENR 4.1 に無く、ここにしかない(立川 TNT・横田 YLT・大島空港 OSE・各ILSのLOC等)。
IFRの経路探索で「FIXから評定できる navaid へ飛ぶ」脚を引くのに要る。

使い方: python3 tools/gen_adnav.py   # adnav.json
⚠ 同じIDが複数の飛行場に出ることがある(ILSのLOCなど)。**最初に出たものを採る**
⚠ ENR 4.1 と重複するIDはそちらを優先(経路用の公示位置)
"""
import os, re, sys, json, glob, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
LAT = re.compile(r'(\d{6}(?:\.\d+)?)N')
LON = re.compile(r'(1\d{6}(?:\.\d+)?)E')
TYPE = re.compile(r'\b(VOR/DME|VORTAC|VOR|TACAN|DME|NDB|ILS-LOC|ILS-GP|LOC|GP|LLZ)\b')
ID = re.compile(r'\b([A-Z]{2,3})\b')
SKIP = {'VOR', 'DME', 'GP', 'ILS', 'LOC', 'NDB', 'MHz', 'KHZ', 'THR', 'RWY', 'ELEV', 'AD', 'CH',
        'HR', 'H24', 'UTC', 'NIL', 'PAR', 'ASR', 'LLZ', 'TWR', 'APP', 'ATIS', 'VHF', 'UHF'}


def pdfs():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine/*.pdf',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine/*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f:
            latest = max(os.path.basename(os.path.dirname(os.path.dirname(x))) for x in f)
            return [x for x in f if os.path.basename(os.path.dirname(os.path.dirname(x))) == latest]
    return []


def dms(v, is_lon):
    d = 3 if is_lon else 2
    return round(int(v[:d]) + int(v[d:d+2])/60 + float(v[d+2:])/3600, 6)


def parse_one(pdf):
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
    icao = os.path.basename(pdf)[:4]
    L = txt.split('\n')
    out = []
    on = False
    for i, l in enumerate(L):
        if re.search(r'AD 2\.19', l): on = True; continue
        if re.search(r'AD 2\.2[01]', l): on = False
        if not on: continue
        ml = LAT.search(l)
        if not ml: continue
        # ⚠ 緯度と経度が**別の行**に来る書式が多い(立川 "354807N/" + "1400035E")。次の3行まで見る
        mo = LON.search(l[ml.end():])
        if not mo:
            for j in range(i+1, min(i+4, len(L))):
                mo = LON.search(L[j])
                if mo: break
        if not mo: continue
        head = l[:ml.start()]
        mt = TYPE.search(head)
        # ID は種別の右、座標の左にある2〜3文字の大文字語
        ids = [x for x in ID.findall(head[mt.end():] if mt else head) if x not in SKIP]
        if not ids: continue
        out.append({'id': ids[0], 'icao': icao, 't': (mt.group(1) if mt else ''),
                    'lat': dms(ml.group(1), False), 'lng': dms(mo.group(1), True)})
    return out


def main():
    fs = pdfs()
    if not fs: print('AD2のPDFが無い', file=sys.stderr); sys.exit(1)
    enr = set()
    try:
        js = open(os.path.join(HERE, 'navaids.gen.js'), encoding='utf-8').read()
        enr = {a['id'] for a in json.loads(js[js.index('['):js.rindex(']')+1]) if a.get('id')}
    except Exception: pass
    seen = {}
    for f in fs:
        for r in parse_one(f):
            if r['id'] in enr or r['id'] in seen: continue
            seen[r['id']] = r
    eff = os.path.basename(os.path.dirname(os.path.dirname(fs[0])))
    dst = os.path.join(HERE, '..', 'adnav.json')
    json.dump({'eff': eff, 'src': 'AIP Japan AD 2.19', 'f': seen},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(seen)} 局(ENR 4.1 に無いもの) → adnav.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')
    # FIX の評定欄に出る navaid をどれだけ賄えたか
    try:
        fx = json.load(open(os.path.join(HERE, '..', 'fix.json')))['f']
        need = set()
        for x in fx:
            for mm in re.finditer(r'\d{3}°/[\d.]+NM\s+([A-Z]{2,3})', x.get('brg') or ''): need.add(mm.group(1))
        miss = sorted(need - enr - set(seen))
        print(f'  FIXの評定に出る navaid {len(need)} 種 / 賄えない {len(miss)}: {miss[:20]}')
    except FileNotFoundError: pass


if __name__ == '__main__':
    main()
