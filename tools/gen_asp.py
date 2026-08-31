#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
関東AIP空域ポリゴン生成 (ASP_POLY)
=====================================
AIP Japan (SWIMポータル配布のAD2各飛行場 AD 2.17 / 特別管制区チャート) から
読み取った空域定義を計算幾何でポリゴン化し、index.html の
  /*ASP_POLY_GEN_START*/ ... /*ASP_POLY_GEN_END*/
区間へ JS リテラルとして書き込む。

使い方:
  python3 tools/gen_asp.py            # 生成して tools/asp_poly.gen.js に出力
  python3 tools/gen_asp.py --splice   # さらに index.html へ埋め込み

データソース(AIRAC 2026-07-09):
  管制圏/情報圏 … 各飛行場 AD 2.17 (水平・垂直限界の文言定義)
  東京特別管制区 … RJTT AD2 チャート (56頂点座標表 + 図の区分読解)
  成田特別管制区 … RJAA AD2 チャート (図中DMS座標 + 9.4/5.4NM DMEアーク)
AIRAC更新時: 新しいAD2 PDFで座標・定義に変更がないか確認し、
変わった箇所だけ下のSPECを直して再実行する。
依存: pip install shapely
"""
import json, math, re, sys, os
from shapely.geometry import Point, Polygon, LineString
from shapely.ops import unary_union

NM_DEG = 1/60.0  # 1nm in deg lat

def dms(s):
    """'353312N' / '1394652E' / '354700.91N' → deg"""
    m = re.match(r'^(\d{2,3})(\d{2})(\d{2}(?:\.\d+)?)[NE]$', s)
    d, mi, se = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return d + mi/60 + se/3600

def ll(lat_s, lon_s):
    return (dms(lat_s), dms(lon_s))

# ── 局所平面近似 (equirect, NM単位) ──────────────────────
class Proj:
    def __init__(self, lat0, lon0):
        self.lat0, self.lon0 = lat0, lon0
        self.k = math.cos(math.radians(lat0))
    def xy(self, lat, lon):
        return ((lon-self.lon0)*60*self.k, (lat-self.lat0)*60)
    def latlon(self, x, y):
        return (self.lat0 + y/60, self.lon0 + x/(60*self.k))

BIG = 60.0  # 半平面クリップ用の十分大きい距離(NM)

def circle(p, c, r, n=180):
    cx, cy = p.xy(*c)
    return Point(cx, cy).buffer(r, quad_segs=n//4)

def halfplane(p, through_xy, brg_deg, keep='left'):
    """方位brgの直線(点through通過)の左/右側半平面ポリゴン。
    brg=進行方位(真方位)。keep='left'は進行方向左手側。"""
    th = math.radians(brg_deg)
    dx, dy = math.sin(th), math.cos(th)      # 進行方向
    nx, ny = (-dy, dx) if keep == 'left' else (dy, -dx)  # 保持側法線
    x0, y0 = through_xy
    a = (x0 - dx*BIG, y0 - dy*BIG)
    b = (x0 + dx*BIG, y0 + dy*BIG)
    c = (b[0] + nx*BIG*2, b[1] + ny*BIG*2)
    d = (a[0] + nx*BIG*2, a[1] + ny*BIG*2)
    return Polygon([a, b, c, d])

def offset_pt(xy, brg_deg, dist):
    th = math.radians(brg_deg)
    return (xy[0] + math.sin(th)*dist, xy[1] + math.cos(th)*dist)

def bent_side(p, through_xy, brg1, brg2, keep_brg):
    """点から brg1 / brg2 に伸びる折れ線の keep_brg 方位側の領域。"""
    x0, y0 = through_xy
    a = offset_pt(through_xy, brg1, BIG)
    b = offset_pt(through_xy, brg2, BIG)
    far = offset_pt(through_xy, keep_brg, BIG*2)
    fa = (a[0]+far[0]-x0, a[1]+far[1]-y0)
    fb = (b[0]+far[0]-x0, b[1]+far[1]-y0)
    return Polygon([a, (x0, y0), b, fb, (far[0], far[1]), fa])

def arc_pts(p, c, r, lat_a, lon_a, lat_b, lon_b, n=48):
    """中心c半径rの円弧: a→b を短弧でサンプル (xyタプル列)。"""
    cx, cy = p.xy(*c)
    ax, ay = p.xy(lat_a, lon_a); bx, by = p.xy(lat_b, lon_b)
    ta = math.atan2(ax-cx, ay-cy); tb = math.atan2(bx-cx, by-cy)
    d = (tb - ta) % (2*math.pi)
    if d > math.pi: d -= 2*math.pi   # 短弧
    return [(cx + r*math.sin(ta + d*i/n), cy + r*math.cos(ta + d*i/n))
            for i in range(n+1)]

def arc_between(p, c, a, b, n=None):
    """中心cのまわりで **点aから点bへ、半径を線形補間しながら**短弧を刻む(xy列)。
       ⚠ arc_pts() は公称半径で描くので、AIPの頂点が秒丸めで±0.05NMずれていると
         隣の区画との境界に隙間ができる。**頂点を必ず通す**こちらを使う
         (中部のCBE 5NM弧が公称と0.05NM食い違っていた)"""
    cx, cy = p.xy(*c); ax, ay = p.xy(*a); bx, by = p.xy(*b)
    ra = math.hypot(ax-cx, ay-cy); rb = math.hypot(bx-cx, by-cy)
    ta = math.atan2(ax-cx, ay-cy); tb = math.atan2(bx-cx, by-cy)
    d = (tb - ta) % (2*math.pi)
    if d > math.pi: d -= 2*math.pi          # 短弧
    if n is None: n = max(24, int(abs(math.degrees(d))/0.6))
    return [(cx + (ra+(rb-ra)*i/n)*math.sin(ta+d*i/n),
             cy + (ra+(rb-ra)*i/n)*math.cos(ta+d*i/n)) for i in range(n+1)]


def arc_by_endpoints(p, a, b, r, center_side, n=48):
    """端点a,b・半径r・中心が弦のどちら側(center_side='NW'等の方位)かで弧を決めサンプル。"""
    ax, ay = p.xy(*a); bx, by = p.xy(*b)
    mx, my = (ax+bx)/2, (ay+by)/2
    ch = math.hypot(bx-ax, by-ay)
    h = math.sqrt(max(r*r - (ch/2)**2, 0))
    ux, uy = (bx-ax)/ch, (by-ay)/ch
    for s in (1, -1):
        cx, cy = mx - s*uy*h, my + s*ux*h
        brg = math.degrees(math.atan2(cx-mx, cy-my)) % 360
        want = {'N':0,'NE':45,'E':90,'SE':135,'S':180,'SW':225,'W':270,'NW':315}[center_side]
        if abs((brg-want+180) % 360 - 180) < 90:
            break
    ta = math.atan2(ax-cx, ay-cy); tb = math.atan2(bx-cx, by-cy)
    d = (tb - ta) % (2*math.pi)
    if d > math.pi: d -= 2*math.pi
    return [(cx + r*math.sin(ta+d*i/n), cy + r*math.cos(ta+d*i/n)) for i in range(n+1)]

def poly_latlon(p, geom, nd=5):
    """shapely Polygon → [[lat,lng],...] (外環のみ)"""
    if geom.is_empty: return []
    if geom.geom_type == 'MultiPolygon':
        geom = max(geom.geoms, key=lambda g: g.area)
    out = []
    for x, y in geom.exterior.coords:
        lat, lon = p.latlon(x, y)
        out.append([round(lat, nd), round(lon, nd)])
    return out

# ⚠ 0.02NM(=37m)まで間引くと **地図を拡大したとき円がカクカクに見える**。
#   ズーム16では37mが15pxになるので目に付く。真円は点列で持たないことにして
#   (下の is_circle 参照)、残りをこの細かさで持つ。
#   0.02 → 0.002 で頂点は6101→3193に増えるが、真円88個を外に出した分で
#   全体は 137KB → 71KB に減る
def keep_side(p, through_xy, brg_deg, toward_xy):
    """through_xy を通る方位brg_degの直線のうち、toward_xy がある側の半平面。
       ⚠ left/right を手で決めると符号を間違える。**残したい点を渡して選ばせる**"""
    for k in ('left', 'right'):
        h = halfplane(p, through_xy, brg_deg, k)
        if h.contains(Point(*toward_xy)): return h
    raise ValueError('keep_side: toward がどちらの側にも入らない')


def bisector_side(p, a, b):
    """等半径の2円の交点を結ぶ線 = 2中心の垂直二等分線。a側を残す半平面を返す。
       AIPの「◯◯ARPと△△ARPから半径5nmの弧の交点を結ぶ線の南側を除く」型"""
    ax, ay = p.xy(*a); bx, by = p.xy(*b)
    brg = math.degrees(math.atan2(bx-ax, by-ay)) % 360
    return keep_side(p, ((ax+bx)/2, (ay+by)/2), brg+90, (ax, ay))


def geo_circle(p, c, r_nm, n=240):
    """**測地線の円**を作ってから投影する。
       ⚠ circle() は局所平面のバッファなので、原点から遠い中心の大きな円
       (与論の NHC 60NM など)では歪む。遠い円はこちらを使う"""
    la1 = math.radians(c[0]); lo1 = math.radians(c[1]); dr = r_nm*1852.0/6371008.8
    out = []
    for i in range(n):
        b = math.radians(360.0*i/n)
        la2 = math.asin(math.sin(la1)*math.cos(dr) + math.cos(la1)*math.sin(dr)*math.cos(b))
        lo2 = lo1 + math.atan2(math.sin(b)*math.sin(dr)*math.cos(la1),
                               math.cos(dr) - math.sin(la1)*math.sin(la2))
        out.append(p.xy(math.degrees(la2), math.degrees(lo2)))
    return Polygon(out)


def simplify(geom, tol=0.002):
    return geom.simplify(tol, preserve_topology=True)


def is_circle(geom):
    """真円(shapelyのbufferが作った正180角形)なら (中心x, 中心y, 半径NM) を返す。
       ⚠ **点列に落とす前に判定すること**。simplifyを通すと崩れる"""
    if geom.is_empty or geom.geom_type != 'Polygon' or len(geom.interiors): return None
    r = list(geom.exterior.coords)[:-1]
    n = len(r)
    if n < 60: return None
    cx = sum(x for x, y in r)/n; cy = sum(y for x, y in r)/n
    d = [math.hypot(x-cx, y-cy) for x, y in r]
    if max(d) - min(d) > 1e-7*max(d): return None
    return cx, cy, sum(d)/n

# ══════════════════════════════════════════════════════════
# ARP (AD 2.2)
# ══════════════════════════════════════════════════════════
ARP = {
 'RJTT': ll('353312N','1394652E'), 'RJAA': ll('354555N','1402308E'),
 'RJAH': ll('361054N','1402453E'), 'RJTA': ll('352717N','1392700E'),
 'RJTC': ll('354239N','1392412E'), 'RJTE': ll('345915N','1394955E'),
 'RJTJ': ll('355031N','1392438E'), 'RJTK': ll('352342N','1395447E'),
 'RJTL': ll('354756N','1400044E'), 'RJTO': ll('344655N','1392137E'),
 'RJTU': ll('363052N','1395216E'), 'RJTY': ll('354455N','1392055E'),
}

OUT = []  # {n,icao,t,up,lo,rmk,pts}

def emit(n, icao, t, up, lo, rmk, p, geom_or_pts):
    # ⚠ **差分を取ると図形が2つ以上に割れることがある**(鹿屋の≤5000が2片)。
    #   poly_latlon は最大の1片しか返さないので、ここで割ってから渡す。
    #   黙って消えると「面積を足しても円にならない」形で出る
    if not isinstance(geom_or_pts, list) and geom_or_pts.geom_type == 'MultiPolygon':
        for g in sorted(geom_or_pts.geoms, key=lambda q: -q.area):
            if g.area > 0.05:            # NM² 未満の破片は捨てる
                emit(n, icao, t, up, lo, rmk, p, g)
        return
    rec = dict(n=n, icao=icao, t=t, up=up, lo=lo, rmk=rmk)
    if not isinstance(geom_or_pts, list):
        c = is_circle(geom_or_pts)
        if c:   # 真円は中心と半径だけ持つ。描画は L.circle(canvasのctx.arc)で滑らか
            la, lo_ = p.latlon(c[0], c[1])
            rec['c'] = [round(la, 6), round(lo_, 6)]
            rec['r'] = round(c[2]*1852.0, 1)
            OUT.append(rec); return
    if isinstance(geom_or_pts, list):
        pts = [[round(a,5), round(b,5)] for a,b in
               (p.latlon(x,y) for x,y in geom_or_pts)]
    else:
        pts = poly_latlon(p, simplify(geom_or_pts))
    if len(pts) < 4:
        print(f'!! skip {n}: empty', file=sys.stderr); return
    rec['pts'] = pts
    OUT.append(rec)

# ══════════════════════════════════════════════════════════
# 管制圏 (CTR) / 情報圏 — AD 2.17 文言定義より
# ══════════════════════════════════════════════════════════

def gen_ctrs():
    # ---- 東京(羽田) RJTT: 5nm円 ≤3000 ----
    p = Proj(*ARP['RJTT'])
    emit('東京 CTR','RJTT','ctr',3000,0,'Tokyo Tower 118.1/124.35', p,
         circle(p, ARP['RJTT'], 5))

    # ---- 成田 RJAA: 5nm円 + 北東延長 ≤3000 ----
    p = Proj(*ARP['RJAA'])
    ext = Polygon([p.xy(*ll(a,b)) for a,b in [
        ('354826N','1401749E'),('355054N','1402341E'),
        ('355238N','1402225E'),('354957N','1401647E')]])
    emit('成田 CTR','RJAA','ctr',3000,0,'Narita Tower 118.2', p,
         unary_union([circle(p, ARP['RJAA'], 5), ext]))

    # ---- 百里 RJAH: 5nm円を2本の線で3分割 ----
    p = Proj(*ARP['RJAH'])
    cir = circle(p, ARP['RJAH'], 5)
    l1a, l1b = p.xy(*ll('361553N','1402433E')), p.xy(*ll('360600N','1402339E'))
    brg1 = math.degrees(math.atan2(l1b[0]-l1a[0], l1b[1]-l1a[1]))
    l2a, l2b = p.xy(*ll('360957N','1402401E')), p.xy(*ll('360739N','1402935E'))
    brg2 = math.degrees(math.atan2(l2b[0]-l2a[0], l2b[1]-l2a[1]))
    west  = halfplane(p, l1a, brg1, 'right')   # 南向き線の右=西側
    east  = halfplane(p, l1a, brg1, 'left')
    south = halfplane(p, l2a, brg2, 'right')   # 東南東向き線の右=南側
    north = halfplane(p, l2a, brg2, 'left')
    emit('百里 CTR (西)','RJAH','ctr',3000,0,'Hyakuri Tower 118.025', p, cir & west)
    emit('百里 CTR (南東)','RJAH','ctr',6000,0,'Hyakuri Tower 118.025 / 上限6000exc', p, cir & east & south)
    emit('百里 CTR (北東)','RJAH','ctr',6000,0,'Hyakuri Tower 118.025', p, cir & east & north)

    # ---- 厚木 RJTA: 5nm円, 西帯のみ1700以上 ----
    p = Proj(*ARP['RJTA'])
    cir = circle(p, ARP['RJTA'], 5)
    o = p.xy(*ARP['RJTA'])
    w1 = halfplane(p, offset_pt(o, 270, 1.7), 0, 'left')     # 南北線の1.7nm西平行線の西側
    w2 = halfplane(p, offset_pt(o, 310, 3.6), 40, 'left')    # 040/220線の3.6nm西平行線の西側
    band = cir & w1 & w2
    emit('厚木 CTR','RJTA','ctr',6000,0,'Atsugi Tower 128.7', p, cir.difference(band))
    emit('厚木 CTR (西帯 1700-6000)','RJTA','ctr',6000,1700,'Atsugi Tower 128.7 / 下限1700', p, band)

    # ---- 横田/立川/入間 (相互依存) ----
    pY = Proj(*ARP['RJTY'])
    oY = pY.xy(*ARP['RJTY'])
    cT = circle(pY, ARP['RJTC'], 5)   # 立川5nm円 (横田基準投影で計算)
    cJ = circle(pY, ARP['RJTJ'], 5)   # 入間5nm円
    cY = circle(pY, ARP['RJTY'], 5)
    east_line = halfplane(pY, offset_pt(oY, 81, 1.0), 351, 'right')  # 171/351線の1nm東平行線の東側
    inter = cT.exterior.intersection(cJ.exterior)  # 立川・入間円の交点2つ
    ipts = sorted([(g.x, g.y) for g in inter.geoms], key=lambda q: q[0])
    (ix1, iy1), (ix2, iy2) = ipts  # 西側, 東側
    brgI = math.degrees(math.atan2(ix2-ix1, iy2-iy1))
    south_of_I = halfplane(pY, (ix1, iy1), brgI, 'right')
    north_of_I = halfplane(pY, (ix1, iy1), brgI, 'left')
    e38 = pY.xy(*ll('353800N','1392800E'))
    brgE = math.degrees(math.atan2(e38[0]-ix2, e38[1]-iy2))
    west_of_E = halfplane(pY, (ix2, iy2), brgE, 'right')  # 南下方向の右手=西側
    tachikawa = cT & east_line & south_of_I & west_of_E
    iruma     = cJ & east_line & north_of_I
    yokota    = cY.difference(tachikawa).difference(iruma)
    emit('立川 CTR','RJTC','ctr',3000,0,'Tachikawa Tower 118.85', pY, tachikawa)
    emit('入間 CTR','RJTJ','ctr',6000,0,'Iruma Tower 122.05/126.2', pY, iruma)
    emit('横田 CTR','RJTY','ctr',3000,0,'Yokota Tower 134.3 / 上限3000AGL(標高463ft)', pY, yokota)

    # ---- 木更津 RJTK: 折れ線3本の南側で3帯 ----
    p = Proj(*ARP['RJTK'])
    cir = circle(p, ARP['RJTK'], 5)
    A = bent_side(p, p.xy(*ll('352547N','1394929E')), 261.15, 54.17, 165)  # 南側
    B = bent_side(p, p.xy(*ll('352345N','1395116E')), 261.15, 54.17, 165)
    C = bent_side(p, p.xy(*ll('352232N','1395221E')), 261.15, 54.17, 165)
    # 3volumeは南側条件の入れ子: A-B帯≤1000 / B-C帯≤1500 / C以南≤2000 (円北側はCTR外)
    emit('木更津 CTR (北帯 ≤1000)','RJTK','ctr',1000,0,'Kisarazu Tower 126.2', p, cir & A.difference(B))
    emit('木更津 CTR (中帯 ≤1500)','RJTK','ctr',1500,0,'Kisarazu Tower 126.2', p, cir & B.difference(C))
    emit('木更津 CTR (南 ≤2000)','RJTK','ctr',2000,0,'Kisarazu Tower 126.2', p, cir & C)

    # ---- 下総 RJTL: 5nm円≤2000 + 北帯≤3500 ----
    p = Proj(*ARP['RJTL'])
    cir = circle(p, ARP['RJTL'], 5)
    org = p.xy(dms('354700.91N'), dms('1401546.75E'))
    north_strip = halfplane(p, offset_pt(org, 344, 3.0), 254, 'right')  # 254°T線の3nm北平行線の北側
    emit('下総 CTR','RJTL','ctr',2000,0,'Shimofusa Tower 126.2/138.3', p, cir.difference(north_strip))
    emit('下総 CTR (北帯 ≤3500)','RJTL','ctr',3500,0,'Shimofusa Tower 126.2/138.3', p, cir & north_strip)

    # ---- 館山 RJTE / 宇都宮 RJTU / 大島 RJTO ----
    p = Proj(*ARP['RJTE'])
    emit('館山 CTR','RJTE','ctr',2000,0,'Tateyama Tower 126.2/122.0', p, circle(p, ARP['RJTE'], 5))
    p = Proj(*ARP['RJTU'])
    emit('宇都宮 CTR','RJTU','ctr',4000,0,'Utsunomiya Tower 126.2', p, circle(p, ARP['RJTU'], 5))
    p = Proj(*ARP['RJTO'])
    emit('大島 情報圏','RJTO','inf',3000,0,'Oshima Radio 118.6', p, circle(p, ARP['RJTO'], 5))

# ══════════════════════════════════════════════════════════
# 東京特別管制区 (RJTT AD2 チャート, 56頂点)
# ══════════════════════════════════════════════════════════
TP = {
 1:(35.667222,139.812778), 2:(35.636389,139.786389), 3:(35.536944,139.881389), 4:(35.537500,139.935000),
 5:(35.585833,139.934722), 6:(35.632778,139.876389), 7:(35.513611,139.871111), 8:(35.470000,139.785833),
 9:(35.432500,139.812500), 10:(35.473611,139.899444), 11:(35.702500,139.843611), 12:(35.537500,139.972778),
 13:(35.616944,139.972500), 14:(35.663611,139.913889), 15:(35.396389,139.838333), 16:(35.437500,139.925278),
 17:(35.726944,139.864722), 18:(35.537778,139.998611), 19:(35.638056,139.998056), 20:(35.684722,139.939722),
 21:(35.374444,139.853889), 22:(35.415556,139.940833), 23:(35.762778,139.895556), 24:(35.538056,140.036667),
 25:(35.669167,140.035833), 26:(35.715833,139.977500), 27:(35.332500,139.883333), 28:(35.373611,139.970556),
 29:(35.769444,139.901111), 30:(35.538056,140.078889), 31:(35.638333,140.078056), 32:(35.750556,139.984722),
 33:(35.765278,139.959167), 34:(35.756389,139.923889), 35:(35.305556,139.902500), 36:(35.346667,139.989722),
 37:(35.777778,140.015833), 38:(35.538333,140.119722), 39:(35.638333,140.118889), 40:(35.720000,140.096389),
 41:(35.766667,140.037778), 42:(35.276667,139.922778), 43:(35.317778,140.010000), 44:(35.815833,139.941389),
 45:(35.666667,139.762222), 46:(35.625556,139.675278), 47:(35.598056,139.694722), 48:(35.636667,139.783333),
 49:(35.688611,139.746667), 50:(35.647222,139.659722), 51:(35.710833,139.732500), 52:(35.678056,139.663056),
 53:(35.648889,139.658611), 54:(35.707500,139.733333), 55:(35.788056,139.679722), 56:(35.754167,139.723056),
}

def gen_tokyo_pca():
    p = Proj(*ARP['RJTT'])
    NR1 = 'Tokyo TCA 124.75(2300-1200)/119.7 副:Tower 118.1 / 24H'
    NR2 = 'Tokyo TCA 124.75/119.7 副:Tower 118.1 / 0600-1000UTC のみ'
    def ring(ids):  # 頂点番号列 → xy列
        return [p.xy(*TP[i]) for i in ids]
    def carc(i, j):  # RJTT 5nm円上の弧 i→j
        return arc_pts(p, ARP['RJTT'], 5, *TP[i], *TP[j])
    def em(name, up, lo, rmk, pts):
        emit(name, 'RJTT', 'pca', up, lo, rmk, p, pts)

    em('東京PCA NR1 中央 (5nm円)', 4000, 3000, NR1+' / 下限3000exc',
       [q for q in circle(p, ARP['RJTT'], 5).exterior.coords])
    em('東京PCA NR1', 4000,  700, NR1, ring([2,1,6,5,4,3]) + carc(3,2))
    em('東京PCA NR1', 5000, 1000, NR1, ring([1,11,14,13,12,4,5,6]))
    em('東京PCA NR1', 6000, 1500, NR1, ring([11,17,20,19,18,12,13,14]))
    em('東京PCA NR1', 6000, 2000, NR1, ring([17,23,26,25,24,18,19,20]))
    em('東京PCA NR1', 6000, 2500, NR1, ring([23,29,34,32,31,30,24,25,26]))
    em('東京PCA NR1', 6000, 3000, NR1, ring([34,33,41,40,39,38,30,31,32]))
    em('東京PCA NR1 (NEXUS)', 6000, 3500, NR1+' / 下限3500exc', ring([29,44,37,41,33,34]))
    em('東京PCA NR1', 4000,  700, NR1, carc(8,7) + ring([10,9]))
    em('東京PCA NR1', 5000, 1000, NR1, ring([9,10,16,15]))
    em('東京PCA NR1', 6000, 1500, NR1, ring([15,16,22,21]))
    em('東京PCA NR1', 6000, 2000, NR1, ring([21,22,28,27]))
    em('東京PCA NR1', 6000, 2500, NR1, ring([27,28,36,35]))
    em('東京PCA NR1', 6000, 3000, NR1, ring([35,36,43,42]))
    em('東京PCA NR2', 4000,  700, NR2+' / 上下限exc', carc(47,48) + ring([45,46]))
    em('東京PCA NR2', 4000, 1000, NR2+' / 上下限exc', ring([46,45,49,50]))
    em('東京PCA NR2', 4500, 1500, NR2+' / 上下限exc', ring([53,49,54,52]))
    em('東京PCA NR2', 6000, 2000, NR2+' / 上下限exc', ring([52,51,56,55]))

# ══════════════════════════════════════════════════════════
# 成田特別管制区 (RJAA AD2 チャート)
# ══════════════════════════════════════════════════════════
NP = {  # 図中DMS座標
 'a1':('360117N','1400838E'), 'a2':('360315N','1401247E'), 'a3':('360317N','1401734E'),
 'a4':('360226N','1402113E'), 'a5':('355950N','1401945E'), 'a6':('360023N','1401723E'),
 'a7':('355705N','1401141E'), 'a8':('355837N','1402038E'), 'a9':('355743N','1401843E'),
 'a10':('355733N','1402446E'),'a11':('355521N','1402026E'),'a12':('355504N','1401308E'),
 'a13':('355319N','1401611E'),'a14':('355130N','1401539E'),'a15':('354957N','1401647E'),
 'a16':('355238N','1402225E'),'a17':('355209N','1401702E'),
 'b1':('354055N','1402315E'), 'b2':('353724N','1402545E'), 'b3':('353507N','1402723E'),
 'b4':('353255N','1402858E'), 'b5':('352849N','1403155E'),
 'c1':('354352N','1402845E'), 'c2':('354008N','1403128E'), 'c3':('353751N','1403308E'),
 'c4':('353539N','1403443E'), 'c5':('353134N','1403739E'),
}

def gen_narita_pca():
    p = Proj(*ARP['RJAA'])
    N = {k: ll(*v) for k, v in NP.items()}
    RMK = 'Tokyo APP 124.4/127.7 副:Narita Tower 118.2 / 24H'
    def ring(ids): return [p.xy(*N[k]) for k in ids]
    def em(name, up, lo, pts, extra=''):
        emit(name, 'RJAA', 'pca', up, lo, RMK+extra, p, pts)
    arc94 = arc_by_endpoints(p, N['a6'], N['a7'], 9.4, 'NW')   # a6→a7
    arc54 = arc_by_endpoints(p, N['a9'], N['a12'], 5.4, 'NW')  # a9→a12
    em('成田PCA', 6000, 3000, ring(['a1','a2','a3','a4','a5','a6']) + arc94)
    em('成田PCA', 6000, 2000, arc94[::-1] + ring(['a6','a5','a8','a9']) + arc54 + [p.xy(*N['a12'])])
    em('成田PCA', 6000, 1500, arc54[::-1] + ring(['a9','a11','a13','a17','a14']))
    em('成田PCA', 6000,  700, ring(['a11','a16','a15','a14','a17','a13']))
    em('成田PCA', 6000, 3000, ring(['a9','a8','a10','a16','a11']))
    arc5 = arc_pts(p, ARP['RJAA'], 5, *N['b1'], *N['c1'])
    em('成田PCA', 4000,  700, arc5 + ring(['c1','c2','b2']))
    em('成田PCA', 5000, 1500, ring(['b2','c2','c3','b3']))
    em('成田PCA', 6000, 2000, ring(['b3','c3','c4','b4']))
    em('成田PCA', 6000, 3000, ring(['b4','c4','c5','b5']))

# ══════════════════════════════════════════════════════════
# 全国CTR/情報圏(関東以外) — AD 2.17 の半径から概略円で「単純に追加」
# データは tools/natl_ctr.json (別途 gen_natl_ctr で全AD2から抽出済み)
# ══════════════════════════════════════════════════════════
def gen_natl():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, 'natl_ctr.json')
    if not os.path.exists(path):
        print('!! natl_ctr.json なし: 全国空域はスキップ', file=sys.stderr); return
    data = json.load(open(path))
    ARPS = {x['icao']: (x['lat'], x['lng']) for x in data}

    # ── AD 2.17 で分割/除外が明記された空域の正確な形状 ──
    # (隣接飛行場どうしが重ならないよう半平面クリップ・円の差分で表現)
    def ov_RJNY(p, c, r):   # 静浜: 104/292°T線の北側
        return circle(p, c, r) & halfplane(p, p.xy(dms('344602N'), dms('1381946E')), 292, 'right')
    def ov_RJNS(p, c, r):   # 静岡: 同じ線の南側(静浜と背中合わせ)
        return circle(p, c, r) & halfplane(p, p.xy(dms('344602N'), dms('1381946E')), 292, 'left')
    def ov_RJNG(p, c, r):   # 岐阜: 名古屋5nmを除外
        return circle(p, c, r).difference(circle(p, ARPS['RJNA'], 5))
    def ov_RJFR(p, c, r):   # 北九州: 築城CTRを除外
        return circle(p, c, r).difference(circle(p, ARPS['RJFZ'], 5))
    def ov_RODN(p, c, r):   # 嘉手納: 普天間CTR(ROTM ARP 261614.5N/1274452.97E)を除外
        return circle(p, c, r).difference(circle(p, (dms('261614.50N'), dms('1274452.97E')), 5))
    def ov_RJSU(p, c, r):   # 霞目: ARPから092°10'T線の1.7NM南に引いた平行線の北側
        o = p.xy(*c)
        return circle(p, c, r) & halfplane(p, offset_pt(o, 182.17, 1.7), 92.17, 'left')
    def ov_ROAH(p, c, r):   # 那覇: 052°56'/125°31'Tの折れ線の西側
        return circle(p, c, r) & bent_side(p, p.xy(dms('261429N'), dms('1274125E')), 52.93, 125.52, 270)
    def _par_line(p, a, b, off_nm, off_side, keep):
        """a→bを結ぶ線をoff_side方向にoff_nm平行移動し、keep側を残す半平面"""
        ax, ay = p.xy(*a); bx, by = p.xy(*b)
        brg = math.degrees(math.atan2(bx-ax, by-ay)) % 360
        return halfplane(p, offset_pt((ax, ay), brg + off_side, off_nm), brg, keep)
    def ov_RJFA(p, c, r):   # 芦屋: DGC VORTAC–SUOH VOR線の4NM北の平行線の北側
        return circle(p, c, r) & _par_line(p, (33.67621,130.38963), (33.85662,131.0294), 4, -90, 'left')
    def ov_RJFZ(p, c, r):   # 築城: DGC VORTAC–340446N1320850E線の4NM南の平行線の北側
        return circle(p, c, r) & _par_line(p, (33.67621,130.38963),
                                           (dms('340446N'), dms('1320850E')), 4, +90, 'left')
    def ov_RJTS(p, c, r):   # 相馬原(AD3 3.16): 5NM円から「350°T線の西側∩270°T線の北側∩3NM円外」を除外
        o = p.xy(*c)
        notch = (halfplane(p, o, 350, 'left')       # 350°T線の西側
                 & halfplane(p, o, 270, 'right')     # 270°T線の北側
                 & circle(p, c, r).difference(circle(p, c, 3)))  # 3NM円の外側
        return circle(p, c, r).difference(notch)
    # ── 「2つのARPから5nmの弧の交点を結ぶ線」で切るもの ──────────────
    # ⚠ 半径が等しいので、その線は **2つのARPの垂直二等分線**そのもの。
    #   AIPが挙げる相手のARPは分単位に丸めた値だが、AD 2.2の実測ARPを使う
    #   (旭川で0.2NM程度しか動かない。丸め値より実測の方が意図に近い)
    RJEC_ARP = (43.67083, 142.44722)   # 旭川空港(AIP表記 43°40'N142°27'E)
    def ov_RJCA(p, c, r):   # 旭川(陸): 旭川空港との二等分線の南側を除外
        return circle(p, c, r) & bisector_side(p, c, RJEC_ARP)
    def ov_ROMD(p, c, r):   # 南大東: 北大東との二等分線の北側を除外
        return circle(p, c, r) & bisector_side(p, c, (25.94472, 131.32694))
    def ov_RORK(p, c, r):   # 北大東: 南大東との二等分線の南側を除外
        return circle(p, c, r) & bisector_side(p, c, (25.84667, 131.26361))
    # ── 直線・大円で切るもの ────────────────────────────────────
    def ov_ROKJ(p, c, r):   # 久米島: 262714N/1264754E と 261214N/1264754E を結ぶ線の西側
        #   ⚠ 2点は**経度が同じ**(126°47'54"E)。つまり子午線で切っている
        return circle(p, c, r) & keep_side(p, p.xy(dms('262714N'), dms('1264754E')),
                                           0, p.xy(*c))
    def ov_RORY(p, c, r):   # 与論: NHC VORTAC(那覇)から60nmの円の中を除外
        #   ⚠ 中心が64nm離れた60nm円。局所平面のcircle()では歪むので測地線で作る
        return circle(p, c, r).difference(geo_circle(p, (26.2082, 127.64262), 60))
    # ── 上限が2段になっているもの(区画ごとにupを持たせる) ──────────
    def ov_RJOY(p, c, r):   # 八尾
        #   (1) 5nm円 … 1300以下
        #   (2) 5nm円 − 344112N1353304E から4.5nm円 … 2000以下
        #   ⚠ 原文の「(exclude area(1))」を**横の除外**と読むと(2)が空になる。
        #     (1)は5nm円そのものなので、これは**高度の除外**(=(2)は1300〜2000)と
        #     読むしかない。塗り分けは「外側の方が上限が高い」で描く
        #   ⚠ 重ねずに**排他に分ける**。どちらの読みでも「その場所の上限」は
        #     同じ(内側1300 / 外側2000)なので、重ねない方が判定も表示も素直
        inner = circle(p, (dms('344112N'), dms('1353304E')), 4.5)
        return [(' (北西部 ≤1300)', 1300, circle(p, c, r) & inner),
                ('', 2000, circle(p, c, r).difference(inner))]
    def ov_RJFY(p, c, r):   # 鹿屋
        #   5nm円 … 5000以下 / そのうち南東寄りの一部 … 6000以下
        #   「312121N/1305056E を通る077°/257°Tの線の5nm北の平行線の南側」かつ
        #   「HKC VOR–TGE VOR を結ぶ線の4nm東の平行線の東側」
        o = p.xy(dms('312121N'), dms('1305056E'))
        south = keep_side(p, offset_pt(o, 77-90, 5), 77, p.xy(*c))
        HKC, TGE = (31.69722, 130.58294), (30.60216, 130.99153)
        ax, ay = p.xy(*HKC); bx, by = p.xy(*TGE)
        brg = math.degrees(math.atan2(bx-ax, by-ay)) % 360
        east = keep_side(p, offset_pt((ax, ay), brg-90, 4), brg, p.xy(*c))
        hi = circle(p, c, r) & south & east
        return [('', 5000, circle(p, c, r).difference(hi)),
                (' (南東部 ≤6000)', 6000, hi)]
    OVERRIDE = {'RJNY':ov_RJNY,'RJNS':ov_RJNS,'RJNG':ov_RJNG,'RJFR':ov_RJFR,
                'RODN':ov_RODN,'RJSU':ov_RJSU,'ROAH':ov_ROAH,'RJFA':ov_RJFA,'RJFZ':ov_RJFZ,
                'RJTS':ov_RJTS,'RJCA':ov_RJCA,'ROMD':ov_ROMD,'RORK':ov_RORK,'ROKJ':ov_ROKJ,
                'RORY':ov_RORY,'RJOY':ov_RJOY,'RJFY':ov_RJFY}
    # 円のままだと実形状より広い(追加区域や除外がある)ものは注記を出す。
    # ⚠ 残っているのは **関西・神戸・中部・大阪・名古屋**。この5つは AD 2.17 に
    #   番号付き座標の追加空域(特別管制区相当)が並んでいて、東京PCAと同じ手間が要る
    APPROX_NOTE = set()
    # 神戸CTRは真円ではない(弦で2分)。gen_kobe_ctr() が出すのでここでは飛ばす
    SKIP = {'RJBE'}

    for x in data:
        if x['icao'] in SKIP: continue
        p = Proj(x['lat'], x['lng'])
        nm = x['n'] + (' 情報圏' if x['t'] == 'inf' else ' CTR')
        c, r = (x['lat'], x['lng']), x['r_nm']
        if x['icao'] in OVERRIDE:
            geom = OVERRIDE[x['icao']](p, c, r)
            rmk = ('AIP形状(AD 3.16の分割/除外を反映) HARUNA TOWER' if x['icao'] == 'RJTS'
                   else 'AIP形状(AD 2.17の分割/除外を反映)')
        else:
            geom = circle(p, c, r)
            rmk = ('AIP概略円(半径%.0fnm) ※実際は追加区域/除外あり・要AIP確認' % r
                   if x['icao'] in APPROX_NOTE else 'AIP概略円(半径%.0fnm)' % r)
        # OVERRIDEは**上限違いの複数区画**を返すことがある(八尾・鹿屋)
        for sfx, up, g in (geom if isinstance(geom, list)
                           else [('', x.get('up', 0) or 0, geom)]):
            emit(nm + sfx, x['icao'], x['t'], up, 0, rmk, p, g)

# ══════════════════════════════════════════════════════════
# 関西・大阪・神戸・中部・名古屋 の特別管制区(PCA)と神戸CTR
# ══════════════════════════════════════════════════════════
# **AD 2.17 の本文に頂点座標が全部書いてある**(東京PCAと同じ形式)。
# チャートのジオリファレンスは要らない。書いてあるのは
#   「◯項 The airspace bounded by the lines connecting the following points」
#   ＋「The line connecting point(a) to point(b) is the (minor) arc with a
#     radius of R from △△」。弧は**全部 minor arc**だった(検算済み)。
# ⚠ 頂点は秒丸めなので、公称半径で弧を描くと隣の区画と隙間ができる。
#   arc_between()(半径を線形補間)を使って**頂点を必ず通す**こと。
#   中部のCBE 5NM弧は公称と0.05NM(93m)食い違っていた
# ⚠ **神戸だけはCTR自体が真円ではない**。5NM円を(1)-(2)の弦で二分し、
#   小弧側(北の帽子)が2000以下・大弧側が2500以下。
#   「minor arc / major arc」の書き分けがそのまま区画の分け方になっている
PCA_ARC_CTR = {
  'KIX':  (34.43417, 135.23278),      # 関西ARP
  'KOBE': (34.63278, 135.22389),      # 神戸ARP
  'ITM':  (34.78444, 135.43917),      # 大阪(伊丹)ARP
  'IKOMA':(34.686667, 135.551111),    # 344112N/1353304E … 大阪PCAの4.5/9NM弧の中心
                                      #   ⚠ 八尾CTRの4.5NM円と**同じ点**
  'KCE':  (34.630994, 135.228458),    # 神戸VOR/DME(RJBE AD 2.19)
                                      #   ⚠ ENR 4.1に無い(飛行場のnavaid)ので navaids.gen.js にも無い
  'CBE':  (34.858006, 136.803169),    # 中部VOR/DME(RJGG AD 2.19)
  'KCC':  (35.26527, 136.91493),      # 名古屋VORTAC
}

def _pp(s):
    """'343824N1351215E' → (lat, lon)"""
    m = re.match(r'(\d{6}(?:\.\d+)?)N/?(\d{7}(?:\.\d+)?)E', s)
    return (dms(m.group(1)+'N'), dms(m.group(2)+'E'))

PCA_SPEC = {
 'RJBB': dict(nm='関西PCA', t='pca',
   rmk='Kansai APP/Radar 125.5-120.25 副:Kansai Tower 118.2-126.2',
   pts={1:'343824N1351215E',2:'343815N1351930E',3:'343809N1352433E',4:'343520N1352558E',
        5:'343408N1352524E',6:'343147N1352417E',7:'342829N1352245E',8:'342637N1351959E',
        9:'342119N1351202E',10:'341943N1350938E',11:'341827N1350745E',12:'341653N1350524E',
        13:'341449N1350219E',14:'341853N1345820E',15:'342057N1350125E',16:'342231N1350345E',
        17:'342347N1350538E',18:'342520N1350758E',19:'343044N1351603E',20:'343313N1351945E',
        21:'343415N1352014E',22:'343047N1351201E',23:'343306N1351206E'},
   sub=[dict(up=5000, lo=2500, exc=True, ring=[1, {'a':'KOBE','f':2,'t':23}]),
        dict(up=5000, lo=1500, ring=[2,3,4,5,21,20,19,{'a':'KIX','f':19,'t':22},22,
                                     {'a':'KOBE','f':23,'t':2}]),
        dict(up=4000, lo=1000, ring=[5,6,20,21]),
        dict(up=3000, lo=700,  ring=[6,7,8,{'a':'KIX','f':8,'t':19},20]),
        dict(up=4000, lo=700,  ring=[9,10,17,{'a':'KIX','f':18,'t':9}]),
        dict(up=5000, lo=1000, ring=[10,11,16,17]),
        dict(up=7000, lo=1500, ring=[11,12,15,16]),
        dict(up=7000, lo=2000, ring=[12,13,14,15])]),
 'RJOO': dict(nm='大阪PCA', t='pca',
   rmk='Kansai APP/Radar 124.7-120.45 副:Osaka Tower 118.1-126.2',
   pts={1:'344519N1353203E',2:'344223N1352828E',3:'344038N1353034E',4:'344335N1353409E',
        5:'343953N1353128E',6:'344250N1353504E',7:'343930N1353157E',8:'343714N1353028E',
        9:'344005N1353822E',10:'343317N1352752E',11:'343639N1354230E'},
   sub=[dict(up=3000, lo=700,  ring=[{'a':'ITM','f':1,'t':2},3,4]),
        dict(up=4000, lo=1100, ring=[4,3,5,6]),
        dict(up=5000, lo=1300, exc=True, ring=[6,5,7,{'a':'IKOMA','f':8,'t':9}]),
        dict(up=5000, lo=3000, ring=[{'a':'IKOMA','f':9,'t':8},10,{'a':'IKOMA','f':10,'t':11}])]),
 'RJBE': dict(nm='神戸PCA', t='pca',
   rmk='Kansai APP/Radar 121.15-120.85-125.5 副:Kobe Tower 118.5-126.2',
   pts={1:'343931N1350740E',2:'343918N1350445E',3:'343508N1350515E',4:'343523N1350814E',
        5:'343901N1350107E',6:'343449N1350137E',7:'343850N1345842E',8:'343437N1345912E',
        9:'343835N1345531E',10:'343420N1345600E'},
   sub=[dict(up=4000, lo=800,  ring=[1,2,3,{'a':'KOBE','f':4,'t':1}]),
        dict(up=5000, lo=1200, ring=[2,5,6,3]),
        dict(up=5000, lo=1800, ring=[5,7,8,6]),
        dict(up=5000, lo=2500, ring=[7,{'a':'KCE','f':9,'t':10},8])]),
 'RJGG': dict(nm='中部PCA', t='pca',
   rmk='Centrair APP 121.05 / Radar 125.55 副:Centrair Tower 118.85',
   pts={1:'350926N1364634E',2:'350628N1364716E',3:'350436N1364742E',4:'350238N1364810E',
        5:'345942N1364852E',6:'345624N1364939E',7:'344724N1365147E',8:'344406N1365234E',
        9:'344109N1365315E',10:'343911N1365343E',11:'343718N1365410E',12:'343420N1365452E',
        13:'343329N1364801E',14:'343629N1364739E',15:'343811N1364726E',16:'344011N1364710E',
        17:'344310N1364648E',18:'344647N1364620E',19:'345514N1364415E',20:'345845N1364256E',
        21:'350138N1364152E',22:'350333N1364109E',23:'350507N1364034E',24:'350801N1363929E'},
   # ⚠ 各項に a) と b) があり、**北と南で対になった同じ上下限の2区画**になっている
   sub=[dict(up=7000, lo=3000, ring=[{'a':'CBE','f':1,'t':24},23,{'a':'CBE','f':23,'t':2}]),
        dict(up=7000, lo=3000, ring=[11,{'a':'CBE','f':12,'t':13},14,{'a':'CBE','f':14,'t':11}]),
        dict(up=7000, lo=2500, ring=[2,3,22,{'a':'CBE','f':23,'t':2}]),
        dict(up=7000, lo=2500, ring=[10,{'a':'CBE','f':11,'t':14},15]),
        dict(up=7000, lo=1800, ring=[3,4,21,22]),
        dict(up=7000, lo=1800, ring=[9,10,15,16]),
        dict(up=5500, lo=1300, ring=[4,5,20,21]),
        dict(up=5500, lo=1300, ring=[8,9,16,17]),
        dict(up=4000, lo=800,  ring=[5,{'a':'CBE','f':6,'t':19},20]),
        dict(up=4000, lo=800,  ring=[{'a':'CBE','f':18,'t':7},8,17])]),
 'RJNA': dict(nm='名古屋PCA', t='pca',
   rmk='Centrair APP 121.05/119.175 Radar 125.55 副:Nagoya Tower 118.7',
   pts={1:'351103N1370057E',2:'350913N1365637E',3:'350633N1365818E',4:'350824N1370238E',
        5:'350338N1370008E',6:'350531N1370426E'},
   sub=[dict(up=4000, lo=800,  ring=[1,2,3,4]),
        dict(up=5000, lo=1300, ring=[4,3,{'a':'KCC','f':5,'t':6}])]),
}


def gen_pca_natl():
    for icao, sp in PCA_SPEC.items():
        pts = {k: _pp(v) for k, v in sp['pts'].items()}
        p = Proj(*pts[1])
        for s2 in sp['sub']:
            xy = []
            for e in s2['ring']:
                if isinstance(e, int): xy.append(p.xy(*pts[e])); continue
                xy += arc_between(p, PCA_ARC_CTR[e['a']], pts[e['f']], pts[e['t']])
            rmk = sp['rmk'] + (' / 下限%dexc' % s2['lo'] if s2.get('exc') else '')
            emit(sp['nm'], icao, sp['t'], s2['up'], s2['lo'], rmk, p, xy)


def gen_kobe_ctr():
    """神戸CTR。5NM円を(1)-(2)の弦で二分し、小弧側2000 / 大弧側2500"""
    KOBE = PCA_ARC_CTR['KOBE']
    a, b = _pp('344120N1351756E'), _pp('344035N1350815E')
    p = Proj(*KOBE)
    cir = circle(p, KOBE, 5)
    cap = Polygon(arc_between(p, KOBE, a, b))          # 短弧+弦 = 北の帽子
    emit('神戸 CTR (北の帽子 ≤2000)', 'RJBE', 'ctr', 2000, 0,
         'Kobe Tower 118.5/126.2 / 小弧側', p, cir & cap)
    emit('神戸 CTR', 'RJBE', 'ctr', 2500, 0,
         'Kobe Tower 118.5/126.2 / 大弧側', p, cir.difference(cap))


# ══════════════════════════════════════════════════════════
def main():
    gen_ctrs(); gen_tokyo_pca(); gen_narita_pca(); gen_natl()
    gen_pca_natl(); gen_kobe_ctr()
    js = ('/* 自動生成: tools/gen_asp.py — AIP Japan AIRAC 2026-07-09\n'
          '   出典: AD2各飛行場 AD 2.17 / RJTT・RJAA 特別管制区チャート */\n'
          'const ASP_POLY=' + json.dumps(OUT, ensure_ascii=False, separators=(',', ':')) + ';')
    here = os.path.dirname(os.path.abspath(__file__))
    gen_path = os.path.join(here, 'asp_poly.gen.js')
    with open(gen_path, 'w') as f: f.write(js + '\n')
    print(f'{len(OUT)} polygons → {gen_path} ({len(js)//1024}KB)')
    if '--splice' in sys.argv:
        idx = os.path.join(here, '..', 'index.html')
        html = open(idx).read()
        s, e = '/*ASP_POLY_GEN_START*/', '/*ASP_POLY_GEN_END*/'
        i, j = html.index(s), html.index(e)
        html = html[:i+len(s)] + '\n' + js + '\n' + html[j:]
        open(idx, 'w').write(html)
        print(f'spliced into {os.path.normpath(idx)}')

if __name__ == '__main__':
    main()
