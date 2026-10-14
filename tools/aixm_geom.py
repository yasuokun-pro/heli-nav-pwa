# -*- coding: utf-8 -*-
"""
AIXM の空域(tools/aixm_extract.py の airspace.json)から、区画ごとの形と上下限を組み立てる共通部品
======================================================================================
・時間スライスは「その日に有効な BASELINE」(begin ≤ at < end)。PERMDELTA は差分なので使わない
・区画(AirspaceGeometryComponent)は operationSequence の順に:
    BASE / UNION / (無し) … 新しい区画として足す(区画ごとに上限・下限が違う)
    SUBTR                … それまでの区画から**平面で**引く(上下限が重なる区画だけ)
    INTERS               … それまでの区画と重なる部分だけ残す
・形は空域ごとの局所平面(NM)で shapely に載せる。真円は中心+半径のまま持ち、引き算が無ければ真円として返す
  (アプリは真円を L.circle で描く。点列にするとカクカクする・CLAUDE.md §4.1)
"""
import math
from shapely.geometry import Polygon, Point, MultiPolygon
from shapely.ops import unary_union


def active(slices, at):
    b = [s for s in slices if s['interp'] == 'BASELINE' and s['begin'] and s['begin'] <= at and (not s['end'] or s['end'] > at)]
    return max(b, key=lambda s: (s['seq'], s['corr'])) if b else None


def ft(v, uom):
    """上限・下限を ft に。FL は×100。GND/SFC→0、UNL→None、数値でないものは None"""
    if v is None: return None
    if isinstance(v, str):
        return 0 if v.upper() in ('GND', 'SFC') else None
    if uom == 'FL': return int(round(v * 100))
    if uom == 'M': return int(round(v / 0.3048))
    return int(round(v))


class Plane:
    def __init__(self, lat0, lng0):
        self.lat0, self.lng0, self.k = lat0, lng0, math.cos(math.radians(lat0))

    def xy(self, p): return ((p[1] - self.lng0) * 60 * self.k, (p[0] - self.lat0) * 60)
    def ll(self, x, y): return [round(self.lat0 + y / 60, 6), round(self.lng0 + x / 60 / self.k, 6)]


def plane_of(slice_):
    pts = [p for c in slice_['comps'] for r in c.get('rings', []) for p in r] + [ci['c'] for c in slice_['comps'] for ci in c.get('circles', [])]
    if not pts: return None
    return Plane(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def comp_geom(c, P):
    gs = []
    for r in c.get('rings', []):
        g = Polygon([P.xy(p) for p in r])
        gs.append(g if g.is_valid else g.buffer(0))
    for ci in c.get('circles', []):
        gs.append(Point(*P.xy(ci['c'])).buffer(ci['r'], quad_segs=64))
    return unary_union(gs) if gs else None


def band_overlap(a, b):
    alo = a['lo'] if a['lo'] is not None else -1e9; ahi = a['up'] if a['up'] is not None else 1e9
    blo = b['lo'] if b['lo'] is not None else -1e9; bhi = b['up'] if b['up'] is not None else 1e9
    return alo < bhi and blo < ahi


def sections(slice_):
    """→ [{geom(shapely・局所平面), up, lo, loRef, upRef, upUom, loUom, circle:{c,r}|None, subtracted:bool}], Plane"""
    P = plane_of(slice_)
    if P is None: return [], None
    out = []
    for c in sorted(slice_['comps'], key=lambda c: c['seq']):
        g = comp_geom(c, P)
        if g is None or g.is_empty: continue
        lim = {'up': ft(c.get('up'), c.get('upUom')), 'lo': ft(c.get('lo'), c.get('loUom')),
               'upRaw': c.get('up'), 'loRaw': c.get('lo'), 'upUom': c.get('upUom'), 'loUom': c.get('loUom'),
               'upRef': c.get('upRef'), 'loRef': c.get('loRef')}
        op = c.get('op') or 'UNION'
        if op in ('BASE', 'UNION'):
            circ = c['circles'][0] if (len(c.get('circles', [])) == 1 and not c.get('rings')) else None
            out.append({**lim, 'geom': g, 'circle': circ, 'subtracted': False})
        elif op == 'SUBTR':
            # ⚠ 引く側に上下限があれば、**その高度帯の中だけ**引く(TH13-2 は 0〜4000 から 0〜2000 だけを除く)。
            #   帯がはみ出す部分は元の形のまま別の区画として残す
            nxt = []
            for s in out:
                full = (lim['up'] is None and lim['lo'] is None)
                if not full and not band_overlap(s, lim): nxt.append(s); continue
                ng = s['geom'].difference(g)
                if abs(ng.area - s['geom'].area) < 1e-9: nxt.append(s); continue
                if full:
                    nxt.append({**s, 'geom': ng, 'subtracted': True, 'circle': None}); continue
                lo = s['lo'] if s['lo'] is not None else -1e9; up = s['up'] if s['up'] is not None else 1e9
                slo = lim['lo'] if lim['lo'] is not None else -1e9; sup = lim['up'] if lim['up'] is not None else 1e9
                if lo < slo: nxt.append({**s, 'up': lim['lo']})                         # 下にはみ出す帯は元の形
                nxt.append({**s, 'geom': ng, 'lo': max(lo, slo) if max(lo, slo) > -1e9 else s['lo'],
                            'up': min(up, sup) if min(up, sup) < 1e9 else s['up'], 'subtracted': True, 'circle': None})
                if up > sup: nxt.append({**s, 'lo': lim['up']})                          # 上にはみ出す帯も元の形
            out = nxt
        elif op == 'INTERS':
            for s in out:
                s['geom'], s['subtracted'], s['circle'] = s['geom'].intersection(g), True, None
    out = [s for s in out if not s['geom'].is_empty and s['geom'].area > 1e-6]
    return out, P


def rings_ll(geom, P, tol=0.001):
    """shapely(局所平面 NM)→ [[外周, 穴...], ...](緯度経度)。tol NM で間引く(0.001NM ≈ 2m)"""
    polys = [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, 'geoms', []) if isinstance(g, Polygon)]
    out = []
    for pg in polys:
        pg = pg.simplify(tol)
        if pg.is_empty: continue
        out.append([[P.ll(x, y) for x, y in pg.exterior.coords]] + [[P.ll(x, y) for x, y in h.coords] for h in pg.interiors])
    return out


def area_nm2(rings_list_of_lists):
    """[[lat,lng]...] の多角形群 → 面積の和集合(NM²)。比較用。cos は全体で1つ"""
    pts = [p for r in rings_list_of_lists for p in r]
    if not pts: return None
    P = Plane(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    gs = []
    for r in rings_list_of_lists:
        if len(r) < 3: continue
        g = Polygon([P.xy(p) for p in r]); gs.append(g if g.is_valid else g.buffer(0))
    return unary_union(gs), P
