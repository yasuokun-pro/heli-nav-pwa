#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地点略号の無いヘリポート・滑空場 生成 (hp.json)
================================================
出典:
  ヘリポート … AIP **AD 1.4.2 地点略号の無いヘリポート**(座標・標高・寸法)
  飛行場     … AIP **AD 1.4.1 地点略号の無い空港等**
  滑空場     … AIP **ENR 5.5.1 GLIDER ACTIVITIES**(座標・活動時間・運営者)

ICAO位置指示記号を持たないので `ad.json`(AD2/AD3)には入らない。
ヘリの運航では場外の候補として意味があるので別レイヤーで出す。

パースの注意:
  AD 1.4 の表は**縦組みを寝かせた段組**で、名称が座標の前後に散らばる。
  座標行を軸にして前後10行から和名/英名を拾う方式にしている。
  ENR 5.5.1 は素直な表なので、座標のある行から左に名前を取る。

出力: hp.json {"eff":..,"f":[{n,en,lat,lng,t,elev,dim,hr,rmk},...]}
  t='H'ヘリポート / 'A'飛行場 / 'G'滑空場
使い方: python3 tools/gen_hp.py
"""
import re, os, sys, glob, json, subprocess

def dms(la, lo):
    return (round(int(la[0:2]) + int(la[2:4])/60 + float(la[4:])/3600, 5),
            round(int(lo[0:3]) + int(lo[3:5])/60 + float(lo[5:])/3600, 5))


def latest(pat):
    f = sorted(glob.glob(os.path.expanduser(pat)))
    return f[-1] if f else None


def txt(pdf):
    return subprocess.run(['pdftotext', '-layout', pdf, '-'],
                          capture_output=True, text=True).stdout


def parse_ad14(t, start, end, kind):
    """AD 1.4 の段組。座標行の前後から名称・標高・寸法を拾う"""
    a = t.index(start)
    b = t.index(end, a) if end else len(t)
    lines = t[a:b].split('\n')
    out, prev = [], -1
    for i, ln in enumerate(lines):
        m = re.search(r'\b(\d{6}(?:\.\d+)?)N\b', ln)
        if not m: continue
        # 経度は同じ行か数行後ろに出る
        lo = None
        for j in range(i, min(i + 6, len(lines))):
            g = re.search(r'\b(\d{7}(?:\.\d+)?)E\b', lines[j])
            if g: lo = g.group(1); break
        if not lo: continue
        lat, lng = dms(m.group(1), lo)
        # 名称は**座標より左の列**にある。右側には設置者や備考が来るので、
        # 座標の開始位置で切らないと「非公共用」「◯◯航空KK」まで混ざる
        col = m.start()
        # 前の項目の座標行より手前は見ない。窓を広げると隣の名前が混ざる
        near = [x[:col] for x in lines[max(prev + 1, i - 5):i + 4]]
        prev = i
        jp = [re.sub(r'\s+', '', x) for x in near
              if re.search(r'[ぁ-んァ-ヶ一-龥]', x)]
        jp = [x for x in jp if not re.search(r'公共用|飛行場外|離着陸|矩形|円形|備考', x)]
        # 標高の桁が名前の右にはみ出すので末尾の数字を落とす
        jp = [re.sub(r'[\d\.]+$', '', x) for x in jp]
        en = [' '.join(x.split()) for x in near
              if re.fullmatch(r"\s*[A-Z][A-Z0-9 \-'\.･]{2,}\s*", x)]
        rest = ' '.join(lines[i:i+3])[col:]
        el = re.search(r'\((\d{1,5})\)', rest)
        dim = re.search(r'(\d+\s*[×x]\s*\d+)', rest)
        r = {'n': ''.join(jp)[:24] or ' '.join(en)[:24], 't': kind,
             'lat': lat, 'lng': lng}
        if en: r['en'] = ' '.join(en)[:32]
        if el: r['elev'] = int(el.group(1))
        if dim: r['dim'] = dim.group(1).replace(' ', '')
        out.append(r)
    return out


def parse_glider(t):
    """ENR 5.5.1。「和名 / 所在」「英名/place  COORD  時間  備考」の2行組"""
    a = t.rindex('1. GLIDER ACTIVITIES')
    b = re.search(r'ENR 5\.6|BIRD MIGRATION', t[a:])
    seg = t[a:a + (b.start() if b else 20000)]
    lines = seg.split('\n')
    out = []
    for i, ln in enumerate(lines):
        m = re.search(r'(\d{6})N/(\d{7})E', ln)
        if not m: continue
        lat, lng = dms(m.group(1), m.group(2))
        head = ln[:m.start()].strip()
        # 和名は1〜2行上に「◯◯滑空場 / 所在地」の形で載る
        jp = ''
        for k in range(i - 1, max(-1, i - 4), -1):
            if re.search(r'[ぁ-んァ-ヶ一-龥]', lines[k]) and '/' in lines[k]:
                jp = re.sub(r'\s+', '', lines[k].split('/')[0]); break
        tail = ln[m.end():].strip()
        hr = (re.search(r'\b(H[JN24]\*?|\d{4}\s*-\s*\d{4})', tail) or [None, ''])[1]
        out.append({'n': jp or head[:24], 'en': head[:40], 't': 'G',
                    'lat': lat, 'lng': lng, 'hr': hr,
                    'rmk': re.sub(r'\s+', ' ', tail)[:80]})
    return out


def main():
    ad1 = latest('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD1_*.pdf') \
       or latest('~/Downloads/1_AIP (PDF)/*/AD1_*.pdf')
    enr = latest('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/ENR_*.pdf') \
       or latest('~/Downloads/1_AIP (PDF)/*/ENR_*.pdf')
    if not ad1 or not enr:
        print('AIPのPDFが見つかりません', file=sys.stderr); sys.exit(1)
    t1, t2 = txt(ad1), txt(enr)
    out = []
    out += parse_ad14(t1, '1. 地点略号の無い空港等', '2. 地点略号の無いヘリポート', 'A')
    out += parse_ad14(t1, '2. 地点略号の無いヘリポート', 'AD 1.5', 'H')
    out += parse_glider(t2)
    # 同じ座標のものが二重に出ることがあるので丸めて重複を消す
    seen, uniq = set(), []
    for r in out:
        k = (r['t'], round(r['lat'], 4), round(r['lng'], 4))
        if k in seen: continue
        seen.add(k); uniq.append(r)

    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'hp.json')
    json.dump({'eff': os.path.basename(os.path.dirname(ad1)),
               'src': 'AIP Japan AD 1.4.1/1.4.2, ENR 5.5.1', 'f': uniq},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    import collections
    print(f'{len(uniq)} 件 → hp.json ({os.path.getsize(dst)/1024:.0f}KB)')
    print(' 種別:', dict(collections.Counter(r['t'] for r in uniq)))
    for r in uniq[:6]: print(f"  {r['t']} {r['n']:<16}{r['lat']},{r['lng']}")


if __name__ == '__main__': main()
