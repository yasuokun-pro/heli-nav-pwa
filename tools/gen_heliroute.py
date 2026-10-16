#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回転翼機の経路(ヘリの特別有視界飛行経路・ヘリポートの到着出発経路など)を線にする → heliroute.json
==================================================================================================
入力: tools/heli_routes.json(経路の定義)/ vrep.json(Visual REP)/ ad.json(ARP)/ tools/heli_osm.json(川の中心線・目印・OSM)
・点はできるだけ AIP の数値から: Visual REP の表(ARP からの真方位・距離)、navaid のラジアル・距離(磁方位は AIP の MAG VAR で真方位に)
・AIP が地名でしか書いていないもの(多摩川沿い・東京競馬場・大和川…)は OpenStreetMap の位置
・図にしか無い点は図を位置合わせして画素から(charts の基準点。相似 or アフィンを最小二乗で当てる)
⚠ どれも「目安」。Visual REP は距離 0.1NM・方位 1° の丸めで最大 200m 程度、略図(嘉手納)は 1km 程度ずれうる
使い方: python3 tools/gen_heliroute.py   (gen_vrep.py・gen_ad.py の後)
"""
import os, json, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
R_NM = 3440.065


def dest(lat, lng, brg, nm):
    d, b, p1, l1 = nm / R_NM, math.radians(brg), math.radians(lat), math.radians(lng)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return [round(math.degrees(p2), 6), round(math.degrees(l2), 6)]


def fit(ctrl, kind):
    """画素(x 右・y 下)→ 緯度経度。局所平面(m)に相似(sim)かアフィン(aff)を最小二乗で当てる。戻り値: 関数と基準点の残差(m)"""
    lat0 = np.mean([c[2] for c in ctrl]); lng0 = np.mean([c[3] for c in ctrl]); k = math.cos(math.radians(lat0))
    A, B = [], []
    for px, py, la, lo in ctrl:
        e, n, qy = (lo - lng0) * 111320 * k, (la - lat0) * 110574, -py      # ⚠ 画像の y は下向き。反転しないと左右が裏返る
        if kind == 'sim': A += [[px, -qy, 1, 0], [qy, px, 0, 1]]
        else: A += [[px, qy, 1, 0, 0, 0], [0, 0, 0, px, qy, 1]]
        B += [e, n]
    p, *_ = np.linalg.lstsq(np.array(A, float), np.array(B, float), rcond=None)

    def f(px, py):
        qy = -py
        if kind == 'sim': e, n = p[0] * px - p[1] * qy + p[2], p[1] * px + p[0] * qy + p[3]
        else: e, n = p[0] * px + p[1] * qy + p[2], p[3] * px + p[4] * qy + p[5]
        return [round(lat0 + n / 110574, 6), round(lng0 + e / (111320 * k), 6)]
    res = [round(math.hypot((f(px, py)[0] - la) * 110574, (f(px, py)[1] - lo) * 111320 * k)) for px, py, la, lo in ctrl]
    return f, res


def dm(a, b):
    return math.hypot((a[0] - b[0]) * 110574, (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])))


def main():
    S = json.load(open(os.path.join(HERE, 'heli_routes.json')))
    OSM = json.load(open(os.path.join(HERE, 'heli_osm.json')))
    V = {(x['icao'], x['n']): [x['lat'], x['lng']] for x in json.load(open(os.path.join(ROOT, 'vrep.json')))['f']}
    AD = {a['icao']: [a['lat'], a['lng']] for a in json.load(open(os.path.join(ROOT, 'ad.json')))['f']}
    CH = {}

    def pt(r):
        kind, _, rest = r.partition(':')
        if kind == 'rep': ic, n = rest.split(':', 1); return V[(ic, n)]
        if kind == 'ad': return AD[rest]
        if kind == 'll': return [float(x) for x in rest.split(',')]
        if kind == 'rad':
            ll, b, d = rest.split(':'); la, lo = (float(x) for x in ll.split(',')); return dest(la, lo, float(b), float(d))
        if kind == 'osm':
            o = OSM
            for key in rest.split(':'): o = o[key]
            return o
        if kind == 'px':
            c, x, y = rest.split(':'); return CH[c](float(x), float(y))
        raise ValueError(r)
    for c, d in S['charts'].items():
        ctrl = [(x, y, *pt(r)) for x, y, r in d['ctrl']]
        CH[c], res = fit(ctrl, d['kind'])
        print(f'  図 {c}: 基準点 {len(ctrl)} 残差 {res} m')

    def line(spec):
        L = OSM[spec['line']]
        i = min(range(len(L)), key=lambda k: dm(L[k], pt(spec['from']))) if 'from' in spec else 0
        j = min(range(len(L)), key=lambda k: dm(L[k], pt(spec['to']))) if 'to' in spec else len(L) - 1
        return L[i:j + 1] if i <= j else L[j:i + 1][::-1]
    out = []
    for r in S['routes']:
        pts = []
        for p in r['pts']:
            seg = line(p) if isinstance(p, dict) else [pt(p)]
            for q in seg:
                if not pts or dm(pts[-1], q) > 1: pts.append([round(q[0], 6), round(q[1], 6)])
        nm = sum(dm(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) / 1852
        out.append({k: r[k] for k in ('icao', 'id', 'n', 'dir', 'alt', 'note', 'src')} | {'pts': pts, 'nm': round(nm, 1)})
    J = {'src': 'AIP Japan(本文・Visual REP・図)+ © OpenStreetMap contributors', 'f': out}
    json.dump(J, open(os.path.join(ROOT, 'heliroute.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 本 / {len(set(r["icao"] for r in out))} 飛行場 → heliroute.json')
    for r in out: print(f"   {r['id']:16} {r['nm']:5.1f}NM {len(r['pts']):3}点  {r['n']}")


if __name__ == '__main__':
    main()
