#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自衛隊低高度訓練／試験空域 生成 (tra.json)
==========================================
出典: AIP Japan **ENR 5.2.1 自衛隊低高度訓練／試験空域**
      (LOW ALT TRAINING / TESTING AREA FOR JSDF AIRCRAFT)

自衛隊機が最低安全高度以下での訓練を行うためにAIPで公示されている空域。
下限はすべて SFC。区域ごとに上限高度・使用時間(UTC)・管制部隊が定められている。
**民間機の進入が禁止されているわけではない**が、低空を高速で飛ぶ訓練機がいる。

なぜ手書きSPECか:
  AIPの表は「1つのAreaが複数のサブ区画(上限高度が別々)に分かれる」構造で、
  上限高度のセルが縦に結合されていることもある(Area 4の6000は2区画にまたがる)。
  pdftotextの段組出力からこの対応を機械的に読むのは危険なので、
  **座標だけ本文から自動抽出し、区画の構成は表の実物(pdftoppmで画像化)を見て書く**。
  AIRAC更新のたびに ENR 5.2-2〜5.2-3 を目視して差分を確認すること。

出力: tra.json {"eff":..,"f":[{n,up,lo,hr,unit,rmk,pts:[外周,穴,..]},..]}
  pts は**リングの配列**。管制圏を除外した結果、区域の内側に穴があく場合があるため
  (Area 3-1 は相馬原管制圏を完全に内包する)。Leafletの L.polygon はこの形をそのまま扱える。
使い方: python3 tools/gen_tra.py
"""
import re, os, sys, glob, math, subprocess, json

# 円弧の中心。ENR 4.1に載らない飛行場の航法施設は各AD 2.19から取った
ARC_CENTER = {
    'KCC': (35.26527, 136.91493),   # Nagoya VORTAC
    'LHT': (34.74735, 137.71006),   # Hamamatsu TACAN
    'IME': (34.67624, 131.77988),   # Iwami VOR/DME (RJOW AD 2.19)
    'P91': (34.73111, 131.52528),   # Area 9-1 の 344352N/1313131E
}

# 表(ENR 5.2-2〜5.2-3)を目視して起こした区画構成。
#   pt   … 区域内の点番号を結ぶ順
#   arc  … (始点, 終点, 半径NM, 中心) をその区間だけ円弧にする
#   up   … 上限(ft)。下限は全てSFC
SPEC = [
 dict(a=1, n='Area 1',   pt=[1,2,3],            up=5000,
      unit='第7航空団 JSDF-A (百里)'),
 dict(a=2, n='Area 2',   pt=[1,2,3],            up=8000,
      unit='宇都宮航空分校 JSDF-G (宇都宮)'),
 dict(a=3, n='Area 3-1', pt=[1,2,3,4,5],        up=10000, excl=['RJTS'],
      unit='第2輸送航空隊 JSDF-A (入間)', rmk='相馬原管制圏を除く'),
 dict(a=3, n='Area 3-2', pt=[3,2,6],            up=8000,
      unit='第2輸送航空隊 JSDF-A (入間)'),
 dict(a=4, n='Area 4-1', pt=[2,3,12,11],        up=11000,
      arc=[(3,12,40,'KCC')], unit='第11飛行教育団 JSDF-A (静浜)'),
 dict(a=4, n='Area 4-2', pt=[7,8,11,12],        up=7000,
      arc=[(12,7,40,'KCC')], unit='第11飛行教育団 JSDF-A (静浜)'),
 dict(a=4, n='Area 4-3', pt=[4,5,13],           up=6000,
      arc=[(4,5,20,'LHT'),(13,4,40,'KCC')], unit='第11飛行教育団 JSDF-A (静浜)'),
 dict(a=4, n='Area 4-4', pt=[1,2,11,8,9,10],    up=6000, excl=['RJNY'],
      unit='第11飛行教育団 JSDF-A (静浜)', rmk='静浜管制圏を除く'),
 dict(a=4, n='Area 4-5', pt=[5,6,7,13],         up=4000,
      arc=[(5,6,20,'LHT'),(7,13,40,'KCC')], unit='第11飛行教育団 JSDF-A (静浜)'),
 dict(a=5, n='Area 5',   pt=[1,2,3,4],          up=10000,
      arc=[(2,3,40,'KCC')], unit='飛行開発実験団 JSDF-A (岐阜)',
      rmk='6地点の半径2NM・2000ft(AGL)以下を除く'),
 dict(a=6, n='Area 6',   pt=[1,2,3,4,5,6,7],    up=15000,
      unit='第3輸送航空隊 JSDF-A (美保)', rmk='上限はFL150'),
 dict(a=7, n='Area 7',   pt=[1,2,3,4,5],        up=11000,
      arc=[(3,4,9,'IME')], unit='第12飛行教育団 JSDF-A (防府)'),
 dict(a=8, n='Area 8-1', pt=[1,2,3,4],          up=11000,
      unit='小月教育航空群 JSDF-M (小月)'),
 dict(a=8, n='Area 8-2', pt=[5,1,4,6,7],        up=3000,
      unit='小月教育航空群 JSDF-M (小月)'),
 dict(a=9, n='Area 9-1', pt=[1,2,3,4,5],        up=9000,
      arc=[(1,2,9,'P91')], unit='第12飛行教育団 JSDF-A (防府)'),
 dict(a=9, n='Area 9-2', pt=[3,6,7,8,9,10,11,4], up=11000,
      arc=[(6,7,9,'IME')], unit='第12飛行教育団 JSDF-A (防府)',
      rmk='10000ft超は神戸ACCの承認が必要'),
]
HOURS = '2200-1200 DLY (UTC)'


def dms(s):
    m = re.match(r'(\d{2})(\d{2})(\d{2})N/?(\d{3})(\d{2})(\d{2})E', s)
    return (int(m.group(1)) + int(m.group(2))/60 + int(m.group(3))/3600,
            int(m.group(4)) + int(m.group(5))/60 + int(m.group(6))/3600)


def parse_points(seg):
    """Areaごとに {点番号: (lat,lng)} を作る。点番号はArea内でのみ一意"""
    pts, cur = {}, None
    for ln in seg.split('\n'):
        a = re.search(r'\bArea\s+(\d+)\b', ln)
        if a: cur = int(a.group(1)); pts.setdefault(cur, {})
        if cur is None: continue
        for no, c in re.findall(r'\((\d+)\)\s*(\d{6}N/\d{7}E)', ln):
            pts[cur][int(no)] = dms(c)
    return pts


def dist_nm(a, b):
    R = 3440.065; p = math.radians
    return R * 2*math.asin(math.sqrt(
        math.sin(p(b[0]-a[0])/2)**2 +
        math.cos(p(a[0]))*math.cos(p(b[0]))*math.sin(p(b[1]-a[1])/2)**2))


def arc_between(c, p1, p2, r_nm, label='', n=24):
    """中心cからp1→p2への短い方の円弧。

    AIP記載の端点が記載半径に乗っていないことがある(Area 9-1の点(1)は
    9NMのはずが7.9NM)。その場合に記載半径で描くと端点との間に段差が出るので、
    両端の実距離を線形に補間して**AIP記載の2点を必ず通る**曲線にする。
    ずれが無ければ結果は記載どおりの円弧と一致する。
    """
    k = math.cos(math.radians(c[0]))
    def ang(p): return math.atan2(p[0]-c[0], (p[1]-c[1])*k)
    a1, a2 = ang(p1), ang(p2)
    d = (a2 - a1 + math.pi) % (2*math.pi) - math.pi        # 短い方向へ
    r1, r2 = dist_nm(c, p1)/60.0, dist_nm(c, p2)/60.0      # 1NM = 1分
    for r, nm_ in ((r1, 'start'), (r2, 'end')):
        if abs(r*60 - r_nm) > 0.2:
            print(f'  警告 {label}: {nm_}点が中心から {r*60:.2f}NM '
                  f'(AIP記載 {r_nm}NM)。両端を通る曲線で近似した', file=sys.stderr)
    out = []
    for i in range(1, n):
        t = a1 + d * i / n
        r = r1 + (r2 - r1) * i / n
        out.append((c[0] + r*math.sin(t), c[1] + r*math.cos(t)/k))
    return out


def load_ctr(icao):
    """除外する管制圏の形状は index.html の ASP_POLY から借りる"""
    here = os.path.dirname(os.path.abspath(__file__))
    h = open(os.path.join(here, '..', 'index.html')).read()
    m = re.search(r'const ASP_POLY=(\[.*?\]);', h, re.S)
    if not m: return None
    for x in json.loads(m.group(1)):
        if x.get('icao') == icao and x.get('t') in ('ctr', 'inf'):
            return x['pts']
    return None


def main():
    pdf = None
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/ENR_*.pdf',
                '~/Downloads/1_AIP (PDF)/*/ENR_*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: pdf = f[-1]; break
    if not pdf:
        print('ENRのPDFが見つかりません', file=sys.stderr); sys.exit(1)
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'],
                         capture_output=True, text=True).stdout
    a = txt.index('LOW ALT TRAINING / TESTING AREA FOR JSDF')
    m = re.search(r'自衛隊高高度訓練／試験空域|HIGH ALT TRAINING', txt[a:])
    seg = txt[a:a + (m.start() if m else 60000)]
    eff = ' / '.join(dict.fromkeys(re.findall(r'EFF:\s*(\d+\s+\w+\s+\d{4})', seg)))

    PTS = parse_points(seg)
    try:
        from shapely.geometry import Polygon
    except ImportError:
        Polygon = None
        print('shapely が無いので管制圏の除外は行いません', file=sys.stderr)

    out = []
    for sp in SPEC:
        p = PTS.get(sp['a'], {})
        miss = [n for n in sp['pt'] if n not in p]
        if miss:
            print(f'  {sp["n"]}: 点 {miss} がAIP本文に見つからない', file=sys.stderr)
            continue
        arcs = {(f, t): (r, c) for f, t, r, c in sp.get('arc', [])}
        ring = []
        for i, no in enumerate(sp['pt']):
            nxt = sp['pt'][(i+1) % len(sp['pt'])]
            ring.append(p[no])
            key = arcs.get((no, nxt))
            if key:
                ring += arc_between(ARC_CENTER[key[1]], p[no], p[nxt], key[0],
                                    f'{sp["n"]} ({no})→({nxt})')
        rings = [ring]
        if Polygon and sp.get('excl'):
            g = Polygon([(x[1], x[0]) for x in ring]).buffer(0)
            for ic in sp['excl']:
                c = load_ctr(ic)
                if c: g = g.difference(Polygon([(x[1], x[0]) for x in c]).buffer(0))
            if g.geom_type == 'MultiPolygon':
                g = max(g.geoms, key=lambda z: z.area)
            # 除外した管制圏が区域の内側に完全に入っていると「穴」になる。
            # exteriorだけ取ると除外が消えてしまうので interiors も必ず持ち帰る
            rings = [[(y, x) for x, y in g.exterior.coords]] + \
                    [[(y, x) for x, y in h.coords] for h in g.interiors]
            if len(rings) > 1:
                print(f'  {sp["n"]}: 除外により穴 {len(rings)-1} 個')
        out.append({'n': sp['n'], 'up': sp['up'], 'lo': 0, 'hr': HOURS,
                    'unit': sp['unit'], 'rmk': sp.get('rmk', ''),
                    'pts': [[[round(la, 5), round(lo, 5)] for la, lo in r] for r in rings]})

    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'tra.json')
    json.dump({'eff': eff, 'src': 'AIP Japan ENR 5.2.1', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 区画 → tra.json ({os.path.getsize(dst)/1024:.0f}KB) EFF:{eff}')
    for f in out:
        npt = sum(len(r) for r in f['pts'])
        hole = f'穴{len(f["pts"])-1}' if len(f['pts']) > 1 else '   '
        print(f'  {f["n"]:<9} SFC-{f["up"]:>5}ft  {npt:>3}点 {hole}  {f["unit"]}')


if __name__ == '__main__': main()
