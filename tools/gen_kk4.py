#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
民間訓練試験空域 KK4 (関東/甲信越 4-1〜4-8) の細分 生成
========================================================
AIP ENR 5.3.1 の KK 4-2〜4-8 は、座標ではなく
**新幹線・河川・高速道路・国道の中心線**で区切られている:

  4-2 上越/北陸新幹線・東北新幹線・県道38号・東北自動車道
  4-3 (熊谷付近→太田付近の直線)・上越新幹線・県道38号・東北自動車道
  4-4 (春日部東方→大宮北の直線)・東北新幹線・利根川
  4-5 東北自動車道・東北新幹線・利根川
  4-6 (太田付近→小山南西の直線)・東北新幹線・利根川・東北自動車道
  4-7 国道125号・(2本の直線)・利根川・東北新幹線
  4-8 (3本の直線)・国道125号・東北新幹線

そこで **OpenStreetMap から該当の線形を取り**、AIPが与える直線と合わせて
平面グラフを作り、polygonize で面に割る。各面がどの区分かは
「その面の境界を構成する線の組み合わせ」がAIPの記述と一致するかで決める。

  ⚠ 境界線の位置はOSM由来(ODbL)。新幹線・高速・河川の線形自体は精度が高いが、
    AIPが定義した幾何そのものではない。**通報の目安**として使い、
    境界付近では地形図で確認すること。アプリ側にもその旨を出している。

県道38号は **埼玉県道38号 加須鴻巣線**。鴻巣で上越新幹線に、加須で東北自動車道に
接しており、4-2と4-3を分ける線として辻褄が合う(足利千代田線は緯度が北すぎる)。

出力: kk4.json {"src":..,"f":[{n:"4-1",pts:[[lat,lng],..]},..]}
      civ.json の 関東/甲信越 4-1 を置き換える形で gen_civ.py が取り込む
使い方: python3 tools/gen_kk4.py [--cache]
"""
import json, os, sys, time, math, urllib.request

OVERPASS = 'https://overpass-api.de/api/interpreter'
CACHE = '/tmp/kk4_osm.json'
BBOX = (35.88, 139.25, 36.42, 140.06)      # 南,西,北,東

Q = """[out:json][timeout:200];
(
  way["railway"="rail"]["name"~"上越新幹線|北陸新幹線"](%s);
  way["railway"="rail"]["name"="東北新幹線"](%s);
  way["highway"="motorway"]["name"="東北自動車道"](%s);
  way["waterway"="river"]["name"="利根川"](%s);
  way["highway"]["name"="加須鴻巣線"](%s);
  way["highway"]["ref"~"(^|;)125(;|$)"]["name"~"国道125号"](%s);
);
out geom;"""

SRC_OF = {'上越新幹線': 'JOETSU', '北陸新幹線': 'JOETSU', '東北新幹線': 'TOHOKU_SK',
          '東北自動車道': 'TOHOKU_EX', '利根川': 'TONE', '加須鴻巣線': 'R38'}

def dms(s):
    import re
    m = re.match(r'(\d{2})(\d{2})(\d{2})N/(\d{3})(\d{2})(\d{2})E', s)
    return (int(m.group(1)) + int(m.group(2))/60 + int(m.group(3))/3600,
            int(m.group(4)) + int(m.group(5))/60 + int(m.group(6))/3600)

# AIP本文に出てくる直線(始点DMS, 終点DMS, 識別名)
P = {
 'A': (dms('360924N/1392013E'), dms('361333N/1393434E')),   # 4-3 の北辺
 'B': (dms('355946N/1395247E'), dms('355641N/1393723E')),   # 4-4 の南辺
 'C': (dms('361333N/1393434E'), dms('361724N/1394754E')),   # 4-6 の北西辺
 'D': (dms('361056N/1395900E'), dms('360112N/1395848E')),   # 4-7 の東辺
 'E': (dms('360112N/1395848E'), dms('355946N/1395247E')),   # 4-7 の南東辺
 'F': (dms('362011N/1395648E'), dms('361911N/1395848E')),   # 4-8 の北辺
 'G': (dms('361911N/1395848E'), dms('361056N/1395900E')),   # 4-8 の東辺
 'H': (dms('361724N/1394754E'), dms('362011N/1395648E')),   # 4-8 の北西辺
}
# 4-1 は座標で定義される。(1)-(2)だけが上越新幹線の中心線
KK41 = [dms('360911N/1392048E'), dms('355641N/1393723E'),
        dms('355534N/1393148E'), dms('355812N/1393048E')]

# 各区分の境界を構成する線の組み合わせ(AIP本文どおり)
SPEC = {
 '4-2': {'JOETSU', 'TOHOKU_SK', 'R38', 'TOHOKU_EX'},
 '4-3': {'A', 'JOETSU', 'R38', 'TOHOKU_EX'},
 '4-4': {'B', 'TOHOKU_SK', 'TONE'},
 '4-5': {'TOHOKU_EX', 'TOHOKU_SK', 'TONE'},
 '4-6': {'C', 'TOHOKU_SK', 'TONE', 'TOHOKU_EX'},
 '4-7': {'R125', 'D', 'E', 'TONE', 'TOHOKU_SK'},
 '4-8': {'F', 'G', 'R125', 'TOHOKU_SK', 'H'},
}


def fetch():
    if '--cache' in sys.argv and os.path.exists(CACHE):
        return json.load(open(CACHE))
    bb = '%s,%s,%s,%s' % BBOX
    q = Q % ((bb,) * 6)
    req = urllib.request.Request(OVERPASS, data=q.encode(),
                                 headers={'User-Agent': 'heli-nav-pwa/1.0'})
    d = json.loads(urllib.request.urlopen(req, timeout=240).read())
    json.dump(d, open(CACHE, 'w'))
    return d


def comps(g):
    return [x for x in getattr(g, 'geoms', [g]) if x.geom_type == 'LineString']


def chain(parts):
    """断片を近い端点どうしで1本に繋ぐ(県道38号は数本に分かれている)"""
    from shapely.geometry import LineString, Point
    parts = [p for p in parts if p.length > 0]
    while len(parts) > 1:
        bb = None
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                for ei in (0, -1):
                    for ej in (0, -1):
                        d = Point(parts[i].coords[ei]).distance(Point(parts[j].coords[ej]))
                        if bb is None or d < bb[0]: bb = (d, i, j, ei, ej)
        d, i, j, ei, ej = bb
        a = list(parts[i].coords); b = list(parts[j].coords)
        if ei == 0: a.reverse()
        if ej == -1: b.reverse()
        parts = [p for k, p in enumerate(parts) if k not in (i, j)] + [LineString(a + b)]
    return parts[0]


def main():
    from shapely.geometry import LineString, box, Point, Polygon
    from shapely.ops import unary_union, polygonize, nearest_points, split

    els = fetch()['elements']
    raw = {}
    for e in els:
        nm = e.get('tags', {}).get('name', '')
        k = SRC_OF.get(nm) or ('R125' if '国道125号' in nm else None)
        if not k: continue
        raw.setdefault(k, []).append(LineString([(p['lon'], p['lat']) for p in e['geometry']]))
    clip = box(BBOX[1], BBOX[0], BBOX[3], BBOX[2])
    L = {k: unary_union(v).intersection(clip) for k, v in raw.items()}
    for k, (a, b) in P.items():
        L[k] = LineString([(a[1], a[0]), (b[1], b[0])])

    def near(key, p, q):
        """pとqの両方に近い成分を選び、届かない分は同じ路線の隣の断片を継ぎ足す。
        新幹線・高速は上下線が別wayなうえ駅や橋でも切れているので、
        最長成分をそのまま使うと端が数km足りない(4-1の北西端が切れる)"""
        cs = comps(L[key])
        base = min(cs, key=lambda l: l.distance(Point(p)) + l.distance(Point(q)))
        grow = True
        while grow:
            grow = False
            for c in cs:
                if c is base or c.length * 111320 < 500: continue
                for ei in (0, -1):
                    for ej in (0, -1):
                        if Point(base.coords[ei]).distance(Point(c.coords[ej])) * 111320 < 1000:
                            a = list(base.coords); b = list(c.coords)
                            if ei == 0: a.reverse()
                            if ej == -1: b.reverse()
                            cand = LineString(a + b)
                            # 継ぎ足して p・q に近づくときだけ採用(折り返しを防ぐ)
                            if (cand.distance(Point(p)) + cand.distance(Point(q))
                                    < base.distance(Point(p)) + base.distance(Point(q)) - 1e-9):
                                base = cand; cs = [x for x in cs if x is not c]; grow = True
                                break
                    if grow: break
                if grow: break
        return base

    def sub(key, p, q, n=200):
        l = near(key, p, q)
        d1, d2 = l.project(Point(p)), l.project(Point(q))
        lo, hi = min(d1, d2), max(d1, d2)
        pts = [l.interpolate(lo + (hi - lo) * i / n).coords[0] for i in range(n + 1)]
        return pts if d1 < d2 else pts[::-1]

    def xp(a, b):
        g = L[a].intersection(L[b])
        return [p for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Point']



    # ── 東側(4-4〜4-8): 線をそのまま平面グラフにして面に割る ────────────
    faces = [f for f in polygonize(unary_union(list(L.values()))) if f.area * 111 * 111 > 3]

    # ── 4-4: 南辺Bを西へ伸ばして東北新幹線に当て、利根川まで回す ──────────
    #    東北新幹線と東北自動車道の交点(久喜付近)より南では高速道路が区域の
    #    内側を通るため、polygonizeだと高速道路で切れてしまう。
    #    SWIMの空域プロファイルサービスの表示でも、南辺は西に伸びて
    #    その空間まで4-4に含まれている
    B0, B1 = P['B']                      # B0=東端(利根川側) B1=西端(新幹線側)
    _, bw = nearest_points(Point((B1[1], B1[0])), L['TOHOKU_SK'])
    tone_sk = min(xp('TOHOKU_SK', 'TONE'), key=lambda p: abs(p.y - 36.133))
    ring44 = [(bw.x, bw.y), (B1[1], B1[0]), (B0[1], B0[0])] \
        + sub('TONE', (B0[1], B0[0]), (tone_sk.x, tone_sk.y)) \
        + sub('TOHOKU_SK', (tone_sk.x, tone_sk.y), (bw.x, bw.y))
    f44 = Polygon(ring44).buffer(0)
    # 利根川は蛇行して自己交差を生むことがあるので、最大の面だけ採る
    if f44.geom_type == 'MultiPolygon': f44 = max(f44.geoms, key=lambda g: g.area)
    print(f'  4-4 南辺Bの西延長 {Point((B1[1], B1[0])).distance(bw)*111320:.0f}m')
    # 4-4が覆う面はpolygonizeの候補から外す(4-5が4-4の面を取ってしまうため)
    faces = [f for f in faces if not f44.contains(f.representative_point())]

    def bounded_by(f):
        ring = f.exterior; got = set()
        for k, g in L.items():
            if ring.intersection(g.buffer(25 / 111320)).length / ring.length > 0.03: got.add(k)
        return got

    # 区分と面の対応は**全体最適**で決める。順番に貪欲で選ぶと、
    # 4-5{高速,新幹線,利根川}が4-6の面(+線C)を先に取ってしまう
    import itertools
    names = ('4-5', '4-6', '4-7', '4-8')      # 4-4 は後で明示的に組み立てる
    bset = {i: bounded_by(f) for i, f in enumerate(faces)}
    big = sorted(range(len(faces)), key=lambda i: -faces[i].area)[:len(names) + 3]
    bestasg = min(itertools.permutations(big, len(names)),
                  key=lambda pm: sum(len(bset[pm[k]] ^ SPEC[n]) for k, n in enumerate(names)))
    out, used = [('4-4', f44)], set(bestasg)
    for k, name in enumerate(names):
        want = SPEC[name]; i = bestasg[k]; f = faces[i]
        # AIPが境界に挙げていない線で分断された面は、隣を足して1つに戻す。
        # 4-4は東北新幹線と東北自動車道の交点(久喜付近)より南では高速道路が
        # 区域の内側を通るので、そこで切れた帯も4-4に含める(SWIMの表示で確認)。
        # touches()は境界がわずかに重なると偽になるため微小バッファで隣接判定する
        for _ in range(3):
            for j, g in enumerate(faces):
                if j in used or not f.buffer(1e-6).intersects(g): continue
                if bounded_by(g) <= want | {'TOHOKU_EX', 'JOETSU'} and g.area < f.area * 0.5:
                    m = unary_union([f, g]).buffer(1e-6).buffer(-1e-6)
                    if m.geom_type == 'Polygon': f = m; used.add(j)
        out.append((name, f))

    # ── 西側(4-2/4-3): polygonizeでは閉じないので境界を明示して組み立てる ──
    A0, A1 = P['A']
    skex = xp('TOHOKU_SK', 'TOHOKU_EX')[0]              # 久喜付近で新幹線と高速が交差
    josk = max(xp('JOETSU', 'TOHOKU_SK'), key=lambda p: p.y)   # 大宮の分岐
    _, ae = nearest_points(Point((A1[1], A1[0])), L['TOHOKU_EX'])
    _, aw = nearest_points(Point((A0[1], A0[0])), L['JOETSU'])
    ring = [(aw.x, aw.y), (A1[1], A1[0]), (ae.x, ae.y)] \
        + sub('TOHOKU_EX', (ae.x, ae.y), (skex.x, skex.y)) \
        + sub('TOHOKU_SK', (skex.x, skex.y), (josk.x, josk.y)) \
        + sub('JOETSU', (josk.x, josk.y), (aw.x, aw.y))
    west = Polygon(ring).buffer(0)

    r38 = comps(L['R38'])
    ends = [Point(x.coords[i]) for x in r38 for i in (0, -1)]
    a, b = nearest_points(min(ends, key=lambda p: p.distance(L['TOHOKU_EX'])), L['TOHOKU_EX'])
    c, d = nearest_points(min(ends, key=lambda p: p.distance(L['JOETSU'])), L['JOETSU'])
    print(f'  県道38号の延長: 東北道側 {a.distance(b)*111320:.0f}m / 上越新幹線側 '
          f'{c.distance(d)*111320:.0f}m (OSMの経路が届いていない分)')
    cut = chain(r38 + [LineString([a, b]), LineString([c, d])])
    cs = list(cut.coords); p0, p1, q0, q1 = cs[0], cs[1], cs[-1], cs[-2]
    cut = LineString([(p0[0]+(p0[0]-p1[0])*30, p0[1]+(p0[1]-p1[1])*30)] + cs +
                     [(q0[0]+(q0[0]-q1[0])*30, q0[1]+(q0[1]-q1[1])*30)])
    w = sorted((f for f in split(west, cut).geoms if f.area * 111 * 111 > 3),
               key=lambda f: -f.centroid.y)
    out += [('4-3', w[0]), ('4-2', w[1])]            # 県道38号の北が4-3・南が4-2

    # ── 4-1: 座標定義。(1)-(2)だけ上越新幹線の中心線に沿わせる ──────────
    p1, p2 = (KK41[0][1], KK41[0][0]), (KK41[1][1], KK41[1][0])
    ring = sub('JOETSU', p1, p2, 60) + [(KK41[2][1], KK41[2][0]), (KK41[3][1], KK41[3][0])]
    out.append(('4-1', Polygon(ring).buffer(0)))

    # ── 区分どうしの隙間を埋める ─────────────────────────────────────
    # 県道38号がOSMでは東北道まで届かず直線で延長しているため、加須の西に
    # 9km²ほどの隙間が残る。SWIMの表示ではこの空間は4-2側で、境界は
    # 4-5と同じ線(東北自動車道)になっている(ユーザー確認済み)
    GAP_TO = '4-2'
    u = unary_union([f for _, f in out])
    for g in ([u] if u.geom_type == 'Polygon' else list(u.geoms)):
        holes = Polygon(g.exterior).difference(g)
        for h in ([holes] if holes.geom_type == 'Polygon' else list(getattr(holes, 'geoms', []))):
            if h.area * 111 * 111 < 0.2: continue
            for k, (n, f) in enumerate(out):
                if n != GAP_TO: continue
                m = unary_union([f, h]).buffer(1e-7).buffer(-1e-7)
                if m.geom_type == 'MultiPolygon': m = max(m.geoms, key=lambda z: z.area)
                out[k] = (n, m)
                print(f'  隙間 {h.area*111*111:.1f}km² を {n} に取り込み')

    out.sort(key=lambda x: x[0])
    res = [{'n': n, 'pts': [[round(y, 5), round(x, 5)] for x, y in f.exterior.coords]}
           for n, f in out]
    for n, f in out:
        print(f'  {n}: {f.area*111*111:6.0f}km²  中心 {f.centroid.y:.3f}N {f.centroid.x:.3f}E')
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'kk4.json')
    json.dump({'src': 'AIP ENR 5.3.1 + OpenStreetMap (ODbL)', 'f': res},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(res)} 区分 → kk4.json ({os.path.getsize(dst)/1024:.0f}KB)')


if __name__ == '__main__': main()
