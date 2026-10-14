#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自衛隊 低高度訓練/試験空域(ENR 5.2.1)を AIXM から作る → tra.json
==================================================================
入力: aip/aixm_dist/airspace.json / 今の tra.json(区画名 Area 3-1 など・使用時間 hr・部隊 unit の引き継ぎ用)
⚠ AIXM は "AREA 3" に区画(上限の違う部分)が並ぶ。今の tra.json の副区画(Area 3-1/3-2)と**重なりが最大のもの**の名前・時間・部隊を引き継ぐ
⚠ 区画の一部を除く指定(Area 3-1 の相馬原管制圏など)は aixm_geom.sections が引いて穴にする。pts は [外周, 穴…] で持つ
使い方: python3 tools/gen_tra_aixm.py [--at …] [--write]
"""
import os, sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aixm_geom import active, sections, rings_ll, Plane
from shapely.geometry import Polygon

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def poly(rings, P):
    g = Polygon([P.xy(p) for p in rings[0]], [[P.xy(p) for p in h] for h in rings[1:] if len(h) >= 3])
    return g if g.is_valid else g.buffer(0)


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    D = json.load(open(os.path.join(ROOT, 'aip', 'aixm_dist', 'airspace.json')))
    OLD = json.load(open(os.path.join(ROOT, 'tra.json')))['f']
    out = []
    for A in D['airspace']:
        s = active(A['slices'], at)
        if not s or s['localType'] != 'LOW ALT TRAINING/TESTING AREA FOR JSDF AIRCRAFT': continue
        num = re.search(r'(\d+(?:-\d+)?)', s['designator'] or '').group(1)
        cand = [f for f in OLD if re.match(r'Area %s(-|$)' % re.escape(num.split('-')[0]), f['n'])]
        secs, P = sections(s)
        for x in secs:
            for rr in rings_ll(x['geom'], P):
                g = poly(rr, P)
                best, ba = None, 0
                for f in cand:
                    pts = f['pts'] if isinstance(f['pts'][0][0], list) else [f['pts']]
                    a = g.intersection(poly(pts, P)).area
                    if a > ba: best, ba = f, a
                nm = best['n'] if best is not None and ba > 0.5 * g.area else f'Area {num}'
                out.append({'n': nm, 'up': x['up'], 'lo': x['lo'] or 0, 'hr': (best or {}).get('hr', ''), 'unit': (best or {}).get('unit', ''),
                            'rmk': '', 'pts': rr, 'src': 'aixm'})
    out.sort(key=lambda f: [int(v) for v in re.findall(r'\d+', f['n'])])
    print(f'{at} 時点: 低高度訓練空域 {len(out)} 区画:', ', '.join(f"{f['n']}({f['up']})" for f in out))
    if '--write' in sys.argv:
        json.dump({'eff': D['src'].replace('.xml', ''), 'src': 'SWIM AIP データ配信(AIXM 5.1.1)・AIP ENR 5.2.1', 'f': out},
                  open(os.path.join(ROOT, 'tra.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        print('tra.json を更新')


if __name__ == '__main__':
    main()
