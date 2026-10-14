#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自衛隊の高高度訓練/試験空域・回廊・超音速飛行区域を AIXM から作る → jsdfa.json(v6-216 で新規)
==========================================================================================
PDF からは起こしていなかった空域。AIXM(SWIM AIP データ配信)で座標が揃ったので足す。
  hat … HIGH ALT TRAINING/TESTING AREA FOR JSDF AIRCRAFT(63空域。⚠ 名前は「高高度」だが **SFC からの区画もある**: C-1・L・N-1 など)
  cor … 回廊 MTR(12本。8,000ft〜。千歳・三沢・松島・小松・岩国・築城・新田原)
  ssa … 超音速飛行区域(42,000ft〜)
使い方: python3 tools/gen_jsdfa_aixm.py [--at …] [--write]
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aixm_geom import active, sections, rings_ll

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
KIND = {'HIGH ALT TRAINING/TESTING AREA FOR JSDF AIRCRAFT': 'hat', 'SUPERSONIC FLIGHT AREA': 'ssa'}


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    D = json.load(open(os.path.join(ROOT, 'aip', 'aixm_dist', 'airspace.json')))
    out = []
    for A in D['airspace']:
        s = active(A['slices'], at)
        if not s: continue
        k = 'cor' if s['type'] == 'MTR' else KIND.get(s['localType'])
        if not k: continue
        secs, P = sections(s)
        for x in secs:
            for rr in rings_ll(x['geom'], P, tol=0.003):
                out.append({'n': (s['name'] or s['designator']).strip(), 'k': k, 'up': x['up'], 'lo': x['lo'] or 0,
                            **({'loAgl': 1} if x.get('loRef') == 'SFC' and x['lo'] else {}), 'pts': rr})
    print(f'{at} 時点: 高高度訓練 {sum(f["k"]=="hat" for f in out)} / 回廊 {sum(f["k"]=="cor" for f in out)} / 超音速 {sum(f["k"]=="ssa" for f in out)} 区画')
    if '--write' in sys.argv:
        p = os.path.join(ROOT, 'jsdfa.json')
        json.dump({'eff': D['src'].replace('.xml', ''), 'src': 'SWIM AIP データ配信(AIXM 5.1.1)・AIP ENR 5.2', 'f': out},
                  open(p, 'w'), ensure_ascii=False, separators=(',', ':'))
        print('jsdfa.json', os.path.getsize(p) // 1024, 'KB')


if __name__ == '__main__':
    main()
