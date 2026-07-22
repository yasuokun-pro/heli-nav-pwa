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

def simplify(geom, tol=0.02):
    return geom.simplify(tol, preserve_topology=True)

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
    if isinstance(geom_or_pts, list):
        pts = [[round(a,5), round(b,5)] for a,b in
               (p.latlon(x,y) for x,y in geom_or_pts)]
    else:
        pts = poly_latlon(p, simplify(geom_or_pts))
    if len(pts) < 4:
        print(f'!! skip {n}: empty', file=sys.stderr); return
    OUT.append(dict(n=n, icao=icao, t=t, up=up, lo=lo, rmk=rmk, pts=pts))

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
    OVERRIDE = {'RJNY':ov_RJNY,'RJNS':ov_RJNS,'RJNG':ov_RJNG,'RJFR':ov_RJFR,
                'RODN':ov_RODN,'RJSU':ov_RJSU,'ROAH':ov_ROAH,'RJFA':ov_RJFA,'RJFZ':ov_RJFZ}
    # 円のままだと実形状より広い(追加区域や除外がある)ものは注記を出す
    APPROX_NOTE = {'RJBB','RJBE','RJGG','RJOO','RJNA','RJCA','RJOY','RJFY','ROKJ','ROMD','RORK','RORY'}

    for x in data:
        p = Proj(x['lat'], x['lng'])
        nm = x['n'] + (' 情報圏' if x['t'] == 'inf' else ' CTR')
        c, r = (x['lat'], x['lng']), x['r_nm']
        if x['icao'] in OVERRIDE:
            geom = OVERRIDE[x['icao']](p, c, r)
            rmk = 'AIP形状(AD 2.17の分割/除外を反映)'
        else:
            geom = circle(p, c, r)
            rmk = ('AIP概略円(半径%.0fnm) ※実際は追加区域/除外あり・要AIP確認' % r
                   if x['icao'] in APPROX_NOTE else 'AIP概略円(半径%.0fnm)' % r)
        emit(nm, x['icao'], x['t'], x.get('up', 0) or 0, 0, rmk, p, geom)

# ══════════════════════════════════════════════════════════
def main():
    gen_ctrs(); gen_tokyo_pca(); gen_narita_pca(); gen_natl()
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
