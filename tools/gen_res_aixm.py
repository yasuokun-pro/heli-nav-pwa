#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
制限空域・警戒区域・飛行制限区域(ENR 5.1)の**形と上下限だけ**を AIXM で置き換える → res.json
==========================================================================================
名前・種別・調整先(res)・時間(hr)・注記は今の res.json(PDF から起こしたもの)を残す。
⚠ PDF からの版は沖縄の W 区域で読み違いがあった(W-179 NORTH RANGE: PDF 版 112NM² / AIXM 3,104NM²、W-174 は逆に過大)。
⚠ 同じ名前に区画が複数ある(R-116 (1)(2)(3))ときは、重なりが最大の区画に対応させる。AIXM が区画を多く持てば分ける
⚠ 原子力施設(ENR 5.3.2.4)は AIXM と座標が一致したので nuke.json は変えない(2026-10-14 確認)
使い方: python3 tools/gen_res_aixm.py [--at …] [--write]
"""
import os, sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aixm_geom import active, sections, rings_ll, Plane
from shapely.geometry import Polygon

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
key = lambda n: (re.match(r'(RJR\d|[RW]-\d+[A-Z]?)', n or '') or re.match(r'(.*)', (n or '').upper().strip())).group(1)


def poly(pts, P):
    rings = pts if isinstance(pts[0][0], list) else [pts]
    g = Polygon([P.xy(p) for p in rings[0]], [[P.xy(p) for p in h] for h in rings[1:] if len(h) >= 3])
    return g if g.is_valid else g.buffer(0)


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    D = json.load(open(os.path.join(ROOT, 'aip', 'aixm_dist', 'airspace.json')))
    R = json.load(open(os.path.join(ROOT, 'res.json')))
    aix = {}
    for A in D['airspace']:
        s = active(A['slices'], at)
        if not s or not (s['localType'] == '(AIRSPACE RESTRICTIONS)' or s['type'] == 'R'): continue
        if re.match(r'^\d{3}$', s['designator'] or ''): continue            # 原子力は別(nuke.json)
        k = key(s['designator'] if re.match(r'(RJR|[RW]-)', s['designator'] or '') else s['name'])
        aix.setdefault(k, []).append(s)
    out, rep, keep = [], 0, 0
    groups = {}
    for f in R['f']: groups.setdefault(key(f['n']), []).append(f)
    for k, olds in groups.items():
        sl = aix.get(k)
        if not sl: out += olds; keep += len(olds); continue
        pieces = []
        for s in sl:
            secs, P = sections(s)
            for x in secs:
                for rr in rings_ll(x['geom'], P):
                    pieces.append((rr, x))
        allp = [p for rr, _ in pieces for p in rr[0]]
        P = Plane(sum(p[0] for p in allp) / len(allp), sum(p[1] for p in allp) / len(allp))
        # 対応づけは IoU(重なり/和)で1対1に(R-521 の 10km 扇形は 20km 扇形の中にあるので、重なり面積だけだと両方 20km に付く)
        G = [poly(rr, P) for rr, _ in pieces]; O = [poly(f['pts'], P) for f in olds]
        iou = sorted(((g.intersection(o).area / max(g.union(o).area, 1e-9), i, j) for i, g in enumerate(G) for j, o in enumerate(O)), reverse=True)
        pick, ui, uj = {}, set(), set()
        for v, i, j in iou:
            if i in ui or (j in uj and len(pieces) <= len(olds)): continue
            pick[i] = j; ui.add(i); uj.add(j)
        for i, (rr, x) in enumerate(pieces):
            best = dict(olds[pick.get(i, 0)])
            if len(pieces) == 1 and len(olds) > 1:          # AIXM は1つの形にまとめている(R-521 の 20km/10km 扇形)
                best['n'] = re.sub(r'\s*\([^)]*\)\s*$', '', best['n']); best['rmk'] = ''
            out.append({**best, 'up': x['up'], 'lo': x['lo'] or 0, 'pts': rr[0] if len(rr) == 1 else rr, 'src': 'aixm'})
            rep += 1
    print(f'{at} 時点: res.json {len(R["f"])} → {len(out)} 区域(AIXM の形に置き換え {rep} / PDF のまま {keep})')
    import collections
    c = collections.Counter(f['n'] for f in out)
    dup = [k for k, v in c.items() if v > 1]; lost = sorted(set(f['n'] for f in R['f']) - set(c))
    if dup: print('  ⚠ 同じ名前に2区画:', dup)
    if lost: print('  ⚠ 対応が付かず消えた:', lost)
    for f in out:
        o = next((x for x in R['f'] if x['n'] == f['n'] or re.sub(r'\s*\([^)]*\)\s*$', '', x['n']) == f['n']), f)
        if (o['up'], o['lo']) != (f['up'], f['lo']): print('  上下限が変わる:', f['n'], (o['lo'], o['up']), '→', (f['lo'], f['up']))
    if '--write' in sys.argv:
        R['f'] = out; R['src'] = R.get('src', '') + ' + 形状は SWIM AIP データ配信(AIXM 5.1.1) ' + D['src'].replace('.xml', '')
        json.dump(R, open(os.path.join(ROOT, 'res.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        print('res.json を更新')


if __name__ == '__main__':
    main()
