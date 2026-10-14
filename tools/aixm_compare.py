#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIXM(SWIM AIP データ配信)の空域と、今のアプリのデータ(PDF から起こしたもの)を面積で突き合わせる
=====================================================================================
対象: 管制圏・情報圏(ASP_POLY) / 民間訓練試験空域(civ.json) / 自衛隊低高度訓練空域(tra.json) /
     制限空域・警戒区域・飛行制限区域(res.json) / 原子力施設(nuke.json)
出力: 種類ごとに 一致件数・面積差(対称差/AIXM)の中央値と大きいもの
使い方: python3 tools/aixm_compare.py [--at 2026-10-14]
"""
import os, sys, json, re, datetime, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aixm_geom import active, sections, Plane
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
AT = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
D = json.load(open(os.path.join(ROOT, 'aip', 'aixm_dist', 'airspace.json')))
ACT = []
for a in D['airspace']:
    s = active(a['slices'], AT)
    if s: ACT.append(s)


def geom_aixm(slist, P):
    gs = []
    for s in slist:
        secs, Q = sections(s)
        for x in secs:
            # 局所平面が空域ごとに違うので、緯度経度に戻してから共通の平面 P に載せ直す
            for pg in ([x['geom']] if isinstance(x['geom'], Polygon) else list(x['geom'].geoms)):
                ext = [P.xy(Q.ll(*c)) for c in pg.exterior.coords]
                holes = [[P.xy(Q.ll(*c)) for c in h.coords] for h in pg.interiors]
                g = Polygon(ext, holes); gs.append(g if g.is_valid else g.buffer(0))
    return unary_union(gs)


def geom_app(items, P):
    gs = []
    for f in items:
        if f.get('c'):
            gs.append(Point(*P.xy(f['c'])).buffer(f['r'] / 1852, quad_segs=64)); continue
        pts = f.get('pts') or []
        rings = pts if pts and isinstance(pts[0][0], list) else [pts]
        if not rings or len(rings[0]) < 3: continue
        g = Polygon([P.xy(p) for p in rings[0]], [[P.xy(p) for p in h] for h in rings[1:] if len(h) >= 3])
        gs.append(g if g.is_valid else g.buffer(0))
    return unary_union(gs)


def cmp(label, pairs):
    """pairs: [(名前, AIXMの時間スライス群, アプリの要素群)]"""
    res, only_a, only_b = [], [], []
    for name, sl, items in pairs:
        if not sl: only_b.append(name); continue
        if not items: only_a.append(name); continue
        pts = [p for s in sl for c in s['comps'] for r in c['rings'] for p in r] + [ci['c'] for s in sl for c in s['comps'] for ci in c['circles']]
        P = Plane(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        A, B = geom_aixm(sl, P), geom_app(items, P)
        if A.area <= 0: continue
        res.append((A.symmetric_difference(B).area / A.area * 100, name, A.area, B.area))
    res.sort(reverse=True)
    med = statistics.median([r[0] for r in res]) if res else 0
    good = sum(1 for r in res if r[0] < 2)
    print(f'\n## {label}: 照合 {len(res)} 件(差2%未満 {good} 件・中央値 {med:.2f}%)')
    for d, n, a, b in res[:12]:
        if d >= 2: print(f'   {d:7.1f}%  {n:28}  AIXM {a:8.1f}NM²  アプリ {b:8.1f}NM²')
    if only_a: print('   AIXM だけにある:', ', '.join(only_a[:40]), '…' if len(only_a) > 40 else '')
    if only_b: print('   アプリだけにある:', ', '.join(only_b[:40]))


def by(pred):
    return [s for s in ACT if pred(s)]


# 1) 管制圏・情報圏
txt = open(os.path.join(ROOT, 'tools', 'asp_poly.gen.js')).read()
ASP = json.loads(txt[txt.index('['):txt.rindex(']') + 1])
pairs = []
for t, loc in (('ctr', None), ('inf', 'INFORMATION ZONE')):
    aix = by(lambda s: (s['type'] == 'CTR') if t == 'ctr' else (s['localType'] == loc))
    names = sorted(set([s['designator'] for s in aix] + [a['icao'] for a in ASP if a['t'] == t]))
    for ic in names:
        pairs.append((f'{t.upper()} {ic}', [s for s in aix if s['designator'] == ic], [a for a in ASP if a['t'] == t and a['icao'] == ic]))
cmp('管制圏・情報圏(ASP_POLY)', pairs)

# 2) 民間訓練試験空域
RG = {'北海道': 'HK', '東北': 'TH', '関東/甲信越': 'KK', '中部/近畿': 'CK', '中国/四国': 'CS', '九州': 'KS', '下地島': 'SH'}
CIV = json.load(open(os.path.join(ROOT, 'civ.json')))['f']
aix = by(lambda s: s['localType'] == 'CIVIL TRAINING AND TESTING AREA')
pairs = []
names = {}
for f in CIV:
    names.setdefault(RG.get(f['rg'], f['rg']) + f['n'], []).append(f)
for s in aix: names.setdefault(s['designator'], [])
for n, items in sorted(names.items()):
    pairs.append((n, [s for s in aix if s['designator'] == n], items))
cmp('民間訓練試験空域(civ.json)', pairs)

# 3) 自衛隊 低高度訓練/試験空域
TRA = json.load(open(os.path.join(ROOT, 'tra.json')))['f']
aix = by(lambda s: s['localType'] == 'LOW ALT TRAINING/TESTING AREA FOR JSDF AIRCRAFT')
pairs = []
for s in aix:
    m = re.match(r'AREA\s*(\d+)(?:-(\d+))?', s['designator'] or '')
    items = [f for f in TRA if m and re.match(r'Area %s(\b|-)' % m.group(1) + (r'' if not m.group(2) else ''), f['n']) and (not m.group(2) or f['n'] == f'Area {m.group(1)}-{m.group(2)}')]
    pairs.append((s['designator'], [s], items))
cmp('自衛隊 低高度訓練空域(tra.json)', pairs)

# 4) 制限空域・警戒区域・飛行制限区域
RES = json.load(open(os.path.join(ROOT, 'res.json')))['f']
aix = by(lambda s: s['localType'] == '(AIRSPACE RESTRICTIONS)' or s['type'] == 'R')
key = lambda n: (re.match(r'(RJR\d|[RW]-\d+[A-Z]?)', n or '') or re.match(r'(.*)', (n or '').upper().strip())).group(1)
pairs = []
done = set()
for s in aix:
    k = key(s['designator'] if re.match(r'(RJR|[RW]-)', s['designator'] or '') else s['name'])
    if re.match(r'^\d{3}$', s['designator'] or ''): continue          # 原子力は下で
    items = [f for f in RES if key(f['n']) == k]
    pairs.append((k, [s], items)); done.add(k)
for f in RES:
    if key(f['n']) not in done: pairs.append((key(f['n']), [], [f])); done.add(key(f['n']))
cmp('制限空域・警戒区域・RJR(res.json)', pairs)

# 5) 原子力施設
NUKE = json.load(open(os.path.join(ROOT, 'nuke.json')))['f']
aix = by(lambda s: s['localType'] == '(AIRSPACE RESTRICTIONS)' and re.match(r'^\d{3}$', s['designator'] or ''))
pairs = []
for s in aix:
    nm = (s['name'] or '').upper()
    items = [f for f in NUKE if f.get('en') and any(w in nm for w in re.findall(r'[A-Z]{4,}', f['en'].upper())[-1:])]
    pairs.append((s['designator'] + ' ' + nm[:22], [s], items[:1]))
cmp('原子力施設(nuke.json)', pairs)
print('\n(新規) 自衛隊 高高度訓練空域:', len(by(lambda s: s['localType'] == 'HIGH ALT TRAINING/TESTING AREA FOR JSDF AIRCRAFT')),
      '/ 回廊:', len(by(lambda s: s['type'] == 'MTR')), '/ 超音速飛行区域:', len(by(lambda s: s['localType'] == 'SUPERSONIC FLIGHT AREA')))
