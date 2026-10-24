#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ACC セクター・ADIZ・FIR・QNH 適用区域・エンルート待機経路 生成 (geo.json)
======================================================================
出典: 航空情報センター「AIP に関する地図表示用データ」(Shapefile, WGS84, AIRAC ごと)
      aip/geo/<AIRAC>/Shapefile_<AIRAC>/*_EFF<AIRAC>.shp   ⚠ aip/ は .gitignore 済み・公開しない
      説明書: aip/geo/Documents/【説明書】AIPに関する地図表示用データの提供について_*.pdf

制限空域・訓練空域・回廊・通報点などは既に AIXM から起こしているので、ここでは
**アプリにまだ無いもの**だけを取る:
  acc  … ACC セクター(FL335 未満 = ENR 2.1 ATTACHMENT-2)。CS・周波数つき
  adiz … 防空識別圏の外側線・内側線(ADIZ は2本の線の間)
  fir  … 飛行情報区の境界線
  qnh  … QNH 適用区域の境界線
  hold … エンルート待機経路(AIP ENR 3.6)。INBD_TR は磁方位
座標は [lat, lng] で小数5桁(約1m)。

使い方: python3 -I tools/gen_geo.py [AIRAC(例 20261029)]   省略時は aip/geo の最新
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shp_read import read

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
GEO = os.path.join(ROOT, 'aip', 'geo')


def ring(pts, nd=5):
    out = []
    for x, y in pts:
        p = [round(y, nd), round(x, nd)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def freqs(s):
    """'132.35MHz, 301.2MHz, 134.6MHz/Secondary, 121.5MHz/Emergency' → (主, 予備)。非常用は省く"""
    pri, sec = [], []
    for t in (s or '').split(','):
        t = t.strip()
        m = re.match(r'^([\d.]+)MHz(?:/(\w+))?', t)
        if not m:
            continue
        if m.group(2) == 'Emergency':
            continue
        (sec if m.group(2) == 'Secondary' else pri).append(m.group(1))
    return pri, sec


def main():
    eff = sys.argv[1] if len(sys.argv) > 1 else sorted(d for d in os.listdir(GEO) if d.isdigit())[-1]
    S = os.path.join(GEO, eff, 'Shapefile_' + eff) + '/'
    shp = lambda n: read(S + n + '_EFF' + eff)

    acc = []
    for g, a in shp('ACC_Sector_below_FL335'):
        fq = a.get('FREQ') or ''
        # 洋上(Tokyo Radio の HF)は CS 欄が "Fukuoka Control, Tokyo" で、周波数欄も [..] で分かれている
        m = re.search(r'\[Fukuoka Control\](.*?)(\[Tokyo\]|$)', fq)
        pri, sec = freqs(m.group(1) if m else fq)
        acc.append({'n': a['NAME'], 'cs': a.get('CS') or '', 'f': pri, 'f2': sec,
                    'hf': 1 if 'HF' in fq else 0, 'rmk': (a.get('REMARKS') or '').strip(),
                    'pts': [ring(p) for p in g['parts']]})

    def lines(n):
        return [ring(p, 4) for g, a in shp(n) for p in g['parts']]

    def polys(n):
        return [ring(p, 4) for g, a in shp(n) for p in g['parts']]

    hold = []
    for g, a in shp('Enroute_Holding'):
        x, y = g['parts'][0][0]
        hold.append({'n': a['HLDG_POINT'], 'rnav': 1 if a.get('RNAV_HOLD') == 'Y' else 0,
                     'ib': int(a['INBD_TR']), 't': a.get('TURN') or 'R', 'lat': round(y, 6), 'lng': round(x, 6)})
    hold.sort(key=lambda h: h['n'])

    out = {'eff': eff, 'src': 'AIP に関する地図表示用データ(航空情報センター)',
           'acc': acc, 'adiz': {'out': polys('ADIZ_OUTER'), 'in': polys('ADIZ_INNER')},
           'fir': lines('FIR'), 'qnh': lines('QNH_Application_Area'), 'hold': hold}
    p = os.path.join(ROOT, 'geo.json')
    with open(p, 'w') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print('geo.json', os.path.getsize(p), 'bytes  acc', len(acc), 'hold', len(hold), 'eff', eff)


if __name__ == '__main__':
    main()
