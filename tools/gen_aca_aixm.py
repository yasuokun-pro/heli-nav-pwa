#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
進入管制区(ACA)を AIXM(SWIM AIP データ配信)から作る
====================================================
入力: aip/aixm_dist/airspace.json(tools/aixm_extract.py の出力)
     localType = "APPROACH CONTROL AREA" の空域。区画(AirspaceGeometryComponent)ごとに上限・下限・外周を持つ。
出力: aca.json の **ACA の部分だけ**を差し替える(TCA は図から起こしたまま残す)。
     各区画 {n, jp, k:'ACA', icao, up, lo, loAgl?, src:'aixm', pts}
⚠ 時間スライスは「その日に有効な BASELINE」を採る(begin ≤ 日時 < end)。PERMDELTA は差分なので使わない。
  大分・熊本・長崎・函館の ACA は end が切れている(福岡ACAに統合などで廃止)ので出さない
⚠ 下限の基準が SFC(地表)のものがある(福岡ACA の 700ft SFC)。loAgl:1 を付けて画面で「地表から」と出す
⚠ 上限・下限の FL は ft に直す(FL160 → 16000)。アプリの altTxt は 18000 以上を FL 表記にする
使い方:
  python3 tools/gen_aca_aixm.py --compare        # 今の aca.json(図から起こした ACA)と面積で突き合わせるだけ
  python3 tools/gen_aca_aixm.py --write          # aca.json の ACA を差し替える
  --at 2026-10-29  … その日に有効な版で作る(AIRAC の発効日)
"""
import os, sys, json, math, datetime
from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
# AIXM の空域名(designator)→ 飛行場(並び順・ボタンの名前に使う)。飛行場に1対1でないものは名前だけ
NAMES = {
    'TOKYO': ('RJTT', '東京'), 'YOKOTA': ('RJTY', '横田'), 'HYAKURI': ('RJAH', '百里'), 'UTUNOMIYA': ('RJTU', '宇都宮'),
    'HAMAMATSU': ('RJNH', '浜松'), 'CHUBU': ('RJGG', '中部'), 'AKENO': ('RJOE', '明野'), 'KANSAI': ('RJBB', '関西'),
    'TOKUSHIMA': ('RJOS', '徳島'), 'MIHO': ('RJOH', '美保'), 'HIROSHIMA': ('RJOA', '広島'), 'IWAKUNI': ('RJOI', '岩国'),
    'FUKUOKA': ('RJFF', '福岡'), 'TSUIKI': ('RJFZ', '築城'), 'KAGOSHIMA': ('RJFK', '鹿児島'), 'KANOYA': ('RJFY', '鹿屋'),
    'NAHA': ('ROAH', '那覇'), 'SAKISHIMA': ('SAKISHIMA', '先島'), 'CHITOSE': ('RJCC', '千歳'), 'SAPPORO': ('SAPPORO', '札幌'),
    'HIDAKA': ('HIDAKA', '日高'), 'MISAWA': ('RJSM', '三沢'), 'MATUSHIMA': ('RJST', '松島'), 'SENDAI': ('RJSS', '仙台'),
    'NIIGATA': ('RJSN', '新潟'), 'KOMATSU': ('RJNK', '小松'), 'SHIRAKAMI': ('SHIRAKAMI', '白神'),
    'OITA': ('RJFO', '大分'), 'KUMAMOTO': ('RJFT', '熊本'), 'NAGASAKI': ('RJFU', '長崎'), 'HAKODATE': ('RJCH', '函館'),
}


def ft(v, uom):
    if v is None or isinstance(v, str): return None
    return int(round(v * 100)) if uom == 'FL' else int(round(v * 0.3048 / 0.3048)) if uom in ('FT', None) else int(round(v / 0.3048))


def lab(v, uom):
    if v is None: return '?'
    if isinstance(v, str): return v
    return 'FL%03d' % v if uom == 'FL' else '%d' % v


def thin(ring):
    # AIXM は弧を細かい点列で持つ(東京ACAで1,044点)。2m のずれまで間引く(22,096→約9,700点・aca.json が倍に膨らむのを防ぐ)
    from shapely.geometry import LineString
    c = LineString([(p[1], p[0]) for p in ring]).simplify(0.00002).coords
    return [[round(y, 5), round(x, 5)] for x, y in c]


def active(slices, at):
    b = [s for s in slices if s['interp'] == 'BASELINE' and s['begin'] and s['begin'] <= at and (not s['end'] or s['end'] > at)]
    return max(b, key=lambda s: (s['seq'], s['corr'])) if b else None


def build(at):
    d = json.load(open(os.path.join(ROOT, 'aip', 'aixm_dist', 'airspace.json')))
    out, gone = [], []
    for a in d['airspace']:
        if not any(s['localType'] == 'APPROACH CONTROL AREA' for s in a['slices']): continue
        s = active(a['slices'], at)
        nm = next((x['designator'] for x in a['slices'] if x['designator']), '?').strip()
        if not s: gone.append(nm); continue
        icao, jp = NAMES.get(nm, (nm, nm))
        comps = sorted(s['comps'], key=lambda c: c['seq'])
        for c in comps:
            if c.get('op') not in ('BASE', 'UNION', None): print('  ⚠', nm, '扱えない operation', c.get('op')); continue
            for ring in c['rings']:
                up, lo = ft(c.get('up'), c.get('upUom')), ft(c.get('lo'), c.get('loUom'))
                r = {'n': f"{nm} ACA {lab(c.get('lo'), c.get('loUom'))}{' SFC' if c.get('loRef') == 'SFC' else ''}/{lab(c.get('up'), c.get('upUom'))}",
                     'jp': jp + '進入管制区', 'k': 'ACA', 'icao': icao, 'up': up, 'lo': lo, 'src': 'aixm',
                     'pts': thin(ring)}
                if c.get('loRef') == 'SFC' and lo: r['loAgl'] = 1
                if isinstance(c.get('up'), str): r['upTxt'] = c['up']
                if isinstance(c.get('lo'), str): r['loTxt'] = c['lo']
                out.append(r)
    return out, gone, d['src']


def poly(pts, k):
    # ⚠ cos(緯度) は**空港ごとに1つ**に揃える。図形ごとに変えると隣り合う区画がずれて、差が大きく出る
    P = Polygon([(p[1] * k * 60, p[0] * 60) for p in pts])      # NM 平面(局所)
    return P if P.is_valid else P.buffer(0)


def compare(new):
    old = json.load(open(os.path.join(ROOT, 'aca.json')))
    by = {}
    for f in old['f']:
        if f['k'] == 'ACA': by.setdefault(f['icao'], []).append(f)
    nb = {}
    for f in new: nb.setdefault(f['icao'], []).append(f)
    print(f"{'飛行場':10} {'旧区画':>4} {'新区画':>4} {'旧面積':>8} {'新面積':>8} {'差(対称差/新)':>12}")
    for icao in sorted(set(by) | set(nb)):
        allp = [p for f in by.get(icao, []) + nb.get(icao, []) for p in f['pts']]
        k = math.cos(math.radians(sum(p[0] for p in allp) / len(allp)))
        o = unary_union([poly(f['pts'], k) for f in by.get(icao, [])]) if icao in by else None
        n = unary_union([poly(f['pts'], k) for f in nb.get(icao, [])]) if icao in nb else None
        if o is not None and n is not None:
            dif = o.symmetric_difference(n).area / n.area * 100
            print(f"{icao:10} {len(by[icao]):4} {len(nb[icao]):4} {o.area:8.0f} {n.area:8.0f} {dif:11.2f}%")
        else:
            print(f"{icao:10} {len(by.get(icao, [])):4} {len(nb.get(icao, [])):4} {'-' if o is None else round(o.area):>8} {'-' if n is None else round(n.area):>8}   {'新規' if o is None else 'AIXMに無い'}")


def main():
    at = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    if '--at' in sys.argv: at = sys.argv[sys.argv.index('--at') + 1] + 'T00:00:00Z'
    new, gone, src = build(at)
    print(f'{at} 時点: ACA {len(set(f["icao"] for f in new))} 空域 / {len(new)} 区画(AIXM {src})。廃止: {", ".join(gone)}')
    if '--compare' in sys.argv or '--write' not in sys.argv: compare(new)
    if '--write' in sys.argv:
        p = os.path.join(ROOT, 'aca.json')
        A = json.load(open(p))
        A['f'] = [f for f in A['f'] if f['k'] != 'ACA'] + new
        A['pending'] = [x for x in A.get('pending', []) if x.get('k') != 'ACA']
        A['acaSrc'] = 'SWIM AIP データ配信(AIXM 5.1.1) ' + src.replace('.xml', '')
        json.dump(A, open(p, 'w'), ensure_ascii=False, separators=(',', ':'))
        print('aca.json を更新:', len(A['f']), '区画(ACA', len(new), '+ TCA', len(A['f']) - len(new), ')')


if __name__ == '__main__':
    main()
