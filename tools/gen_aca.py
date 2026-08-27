#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
進入管制区・ターミナルコントロールエリア 生成 (aca.json)
========================================================
出典: AIP Japan **各飛行場の AD 2.17 ATS AIRSPACE の添付チャート**
      (◯◯進入管制区 Approach Control Area / ◯◯ターミナルコントロールエリア)

  ⚠ **AD 2.17 の表には座標が無い**。全空港が「SEE ATTACHED CHART」で、
    形状はチャート図にしか無い。ただし図の多くは **(1)(2)… の番号付き座標表**
    を持っていて、そこはテキスト層から機械抽出できる(→ tools/aca_points.json)。
    区画の**繋ぎ方(どの番号をどの順で結ぶか)は図を見ないと分からない**ので、
    座標は自動・構成は手書き、という gen_tra.py と同じ作りにしてある。

  ⚠ **検算を必ず通すこと**。副区画の球面面積の合計が外形と一致しなければ
    読み違えている。横田ACAでは (17)(18)(19) の三角形を取りこぼしていて
    0.3%ずれ、8000区画が (19)→(17)→(18) と回ると分かって0.0000%になった。

  ⚠ 高度の読み方: ラベルは「上の線 / 上限 / 下限 / 下の線」。
    東京ACAの「FL240 / 4000 (EXC 4000)」は上限FL240・下限4000(4000は含まない)。
    **横田ACAのように数値が1つで下線が無い図は上限のみ**で、下限は図に無い。
    無い下限を勝手に GND と決めないこと(lo=None のまま出して注記する)。

出力: aca.json {"eff":..,"f":[{n,jp,k,icao,up,lo,exc,pts},..]}
  k … 'ACA'=進入管制区 / 'TCA'=ターミナルコントロールエリア
使い方: python3 tools/gen_aca.py
"""
import re, os, sys, glob, json, math, subprocess

PT = re.compile(r'\((\d{1,3})\)\s*(\d{6}(?:\.\d+)?)N\s*/?\s*(\d{7}(?:\.\d+)?)E')
R_EARTH = 6371.0088


def dms(la, lo):
    return (round(int(la[0:2]) + int(la[2:4])/60 + float(la[4:])/3600, 6),
            round(int(lo[0:3]) + int(lo[3:5])/60 + float(lo[5:])/3600, 6))


def sph_area(pts):
    """球面上の面積(km²)。**平面近似だと緯度幅の広い外形で誤差が出る**
       (横田で72km²=0.3%ずれた)。検算に使うのでここは近似しない"""
    s = 0.0
    for i in range(len(pts)):
        la1, lo1 = map(math.radians, pts[i])
        la2, lo2 = map(math.radians, pts[(i+1) % len(pts)])
        s += (lo2 - lo1) * (2 + math.sin(la1) + math.sin(la2))
    return abs(s) * R_EARTH * R_EARTH / 2


def ad2_dir():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine'):
        d = sorted(glob.glob(os.path.expanduser(pat)))
        if d: return d[-1]
    return None


def harvest(base):
    """全AD2から ACA/TCA チャートの番号付き座標表を集める"""
    out = {}
    for pdf in sorted(glob.glob(os.path.join(base, '*.pdf'))):
        icao = os.path.basename(pdf).split('__')[0]
        t = subprocess.run(['pdftotext', '-layout', pdf, '-'],
                           capture_output=True, text=True).stdout
        for pg in t.split('\f'):
            head = pg[:900]
            k = ('TCA' if 'Terminal Control Area' in head else
                 'ACA' if 'Approach Control Area' in head else None)
            if not k: continue
            pts = PT.findall(pg)
            if not pts: continue
            d = {int(n): dms(a, b) for n, a, b in pts}
            key = icao + '/' + k
            # 同じ図が複数ページに割れることがあるのでマージする
            out.setdefault(key, {}).update(d)
    return out



# ── チャートのジオリファレンス(区画を読むための補助) ─────────────────
# 図の (1)(2)… ラベルは **pdftotext -bbox-layout でページ上の座標が取れる**。
# 座標表の緯度経度と突き合わせるとアフィン変換が求まり、**真の点位置を図に
# 打ち直した画像**が作れる。ラベルは点から少しずれて置かれるので、
# ラベル位置のまま読むと密集部(東京ACAの(21)〜(30)付近)で必ず取り違える。
#   使い方:
#     pdftotext -bbox-layout -f <page> -l <page> RJTT__*.pdf out.html
#     python3 tools/gen_aca.py --annot RJTT 27   → /tmp/aca_annot.png
# 残差は5〜6pt程度出る(ラベルのオフセット分)。これ以上大きいときは
# 座標表とラベルの対応がずれている。
def annotate(icao, page, base, kind='ACA'):
    """チャート画像に真の点位置を打った画像を作る(区画の読み取り用)"""
    import numpy as np
    from PIL import Image, ImageDraw
    pdf = glob.glob(os.path.join(base, icao + '__*.pdf'))[0]
    subprocess.run(['pdftotext', '-bbox-layout', '-f', str(page), '-l', str(page),
                    pdf, '/tmp/aca_bbox.html'], check=True)
    h = open('/tmp/aca_bbox.html').read()
    W = re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" '
                   r'yMax="([\d.]+)">([^<]*)</word>', h)
    lab = {}
    for x0, y0, x1, y1, t in W:
        m = re.fullmatch(r'\((\d{1,3})\)', t.strip())
        if not m: continue
        y = (float(y0) + float(y1)) / 2
        if y > 560: continue          # 下部の座標一覧は図ではない
        lab.setdefault(int(m.group(1)), ((float(x0)+float(x1))/2, y))
    P = {int(k): v for k, v in
         json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'aca_points.json')))[icao + '/' + kind].items()}
    ks = [k for k in lab if k in P]
    A = np.array([[P[k][1], P[k][0], 1] for k in ks])
    cx = np.linalg.lstsq(A, np.array([lab[k][0] for k in ks]), rcond=None)[0]
    cy = np.linalg.lstsq(A, np.array([lab[k][1] for k in ks]), rcond=None)[0]
    r = np.hypot(A@cx - [lab[k][0] for k in ks], A@cy - [lab[k][1] for k in ks])
    print(f'  ジオリファレンス: {len(ks)}点 残差 平均{r.mean():.1f} 最大{r.max():.1f} pt')
    # ⚠ 前回の画像が残っていると sorted()[-1] が別ページを拾う。毎回消すこと
    for old in glob.glob('/tmp/aca_pg-*.png'): os.remove(old)
    subprocess.run(['pdftoppm', '-png', '-r', '420', '-f', str(page), '-l', str(page),
                    pdf, '/tmp/aca_pg'], check=True)
    png = sorted(glob.glob('/tmp/aca_pg-*.png'))[-1]
    im = Image.open(png).convert('RGB'); d = ImageDraw.Draw(im); S = 420/72.0
    for n, (la, lo) in P.items():
        v = np.array([lo, la, 1.0]); x, y = float(v@cx)*S, float(v@cy)*S
        d.ellipse([x-7, y-7, x+7, y+7], fill=(220, 0, 0))
        d.text((x+9, y-22), str(n), fill=(0, 90, 220))
    im.save('/tmp/aca_annot.png')
    print('  → /tmp/aca_annot.png')

# ── 円弧の扱い ────────────────────────────────────────────────────
# リングの要素は 点番号(int) か、円弧を表す dict:
#   {'arc':(中心lat,中心lon), 'r':半径NM, 'from':点番号 or 方位, 'to':同}
#   {'cut':(中心lat,中心lon), 'r':半径NM, 'seg':(点番号,点番号)}  … 線分と円の交点
NM_M = 1852.0

def _brg(cla, clo, la, lo):
    return math.degrees(math.atan2((lo-clo)*math.cos(math.radians(cla)), la-cla)) % 360

def _arc(cla, clo, r_m, a0, a1, n=48):
    if a1 < a0: a1 += 360
    out = []
    for i in range(n+1):
        a = math.radians(a0 + (a1-a0)*i/n); d = r_m/111320.0
        out.append([round(cla + d*math.cos(a), 6),
                    round(clo + d*math.sin(a)/math.cos(math.radians(cla)), 6)])
    return out

def _cut(cla, clo, r_m, p1, p2):
    """線分 p1-p2 と半径r_mの円の交点(片方が内側・片方が外側の前提)"""
    dist = lambda p: math.hypot((p[0]-cla)*111320.0,
                                (p[1]-clo)*111320.0*math.cos(math.radians(cla)))
    a, b = 0.0, 1.0
    for _ in range(60):
        m = (a+b)/2
        pm = (p1[0]+(p2[0]-p1[0])*m, p1[1]+(p2[1]-p1[1])*m)
        if (dist(p1) < r_m) == (dist(pm) < r_m): a = m
        else: b = m
    m = (a+b)/2
    return [round(p1[0]+(p2[0]-p1[0])*m, 6), round(p1[1]+(p2[1]-p1[1])*m, 6)]

# ── 同心円弧の空域(百里TCA型) ──────────────────────────────────────
# 百里TCAは **中心Cのまわりの同心円弧(5/6/9/12/14.8/19/24/30NM)と放射線**で
# 組まれている。⚠ 中心はAD 2.17のARPではない。30NM弧上の4点
# (28)(29)(18)(20) に円を当てはめると **残差0.00NMで (36.1900,140.4161)** に
# なる(ARPより0.5NM北)。ARPを中心にすると点が±0.7NMずれて弧が合わない。
# リング要素 {'arcp':(a,b)} は「点aから点bへ、Cを中心とする弧」。
# ⚠ 半径は2点の実測値を線形補間する。公称値(例:12NM)に丸めると
#   AIPの頂点座標から最大0.34NMずれるので、頂点は必ず実測値を通す。
#   隣り合う区画は同じ弧を共有するので、これで面積の一致も保たれる。

def _rb(c, p):
    la1, lo1, la2, lo2 = map(math.radians, [c[0], c[1], p[0], p[1]])
    d = 2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 +
        math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2)) * 6371008.8
    y = math.sin(lo2-lo1)*math.cos(la2)
    x = math.cos(la1)*math.sin(la2)-math.sin(la1)*math.cos(la2)*math.cos(lo2-lo1)
    return d, math.degrees(math.atan2(y, x)) % 360

def _pt(c, d_m, b):
    la = math.radians(c[0]); dr = d_m/6371008.8; br = math.radians(b)
    la2 = math.asin(math.sin(la)*math.cos(dr)+math.cos(la)*math.sin(dr)*math.cos(br))
    lo2 = math.radians(c[1]) + math.atan2(math.sin(br)*math.sin(dr)*math.cos(la),
                                          math.cos(dr)-math.sin(la)*math.sin(la2))
    return [round(math.degrees(la2), 6), round(math.degrees(lo2), 6)]

def _arcp(c, p1, p2, n=40):
    r1, b1 = _rb(c, p1); r2, b2 = _rb(c, p2)
    d = (b2-b1) % 360
    if d > 180: d -= 360           # 短い方に回る
    return [_pt(c, r1+(r2-r1)*i/n, b1+d*i/n) for i in range(n+1)]


def build(ring, pts, ctr=None):
    """SPECのリング指定を座標列にする"""
    out = []
    for e in ring:
        if isinstance(e, int): out.append(list(pts[e])); continue
        if 'arcp' in e:
            a, b = e['arcp']
            pa = pts[a] if isinstance(a, int) else a
            pb = pts[b] if isinstance(b, int) else b
            out += _arcp(e.get('c', ctr), pa, pb); continue
        c = e['arc'] if 'arc' in e else e['cut']
        r = e['r'] * NM_M
        if 'cut' in e:
            out.append(_cut(c[0], c[1], r, pts[e['seg'][0]], pts[e['seg'][1]])); continue
        def ang(v):
            if isinstance(v, (int,)) and v in pts: return _brg(c[0], c[1], *pts[v])
            if isinstance(v, dict): return _brg(c[0], c[1], *_cut(c[0], c[1], r,
                                       pts[v['seg'][0]], pts[v['seg'][1]]))
            return float(v)
        out += _arc(c[0], c[1], r, ang(e['from']), ang(e['to']))
    return out


# ── 図を見て起こした区画構成 ───────────────────────────────────────
# ring は座標表の番号を結ぶ順。up/lo は ft(FLxxx は 100倍して入れる)。
# exc=True は「下限の高度自体は含まない(EXC)」の意。
SPEC = {
 'RJTY/ACA': dict(
   # ⚠ **図の数値は下限**。上限は図に無い。
   #   横田の4区画は東京ACAの区画と**座標が完全に一致**していて(重なり100%)、
   #   東京の図では同じ数値が「FL240 / 12000 (EXC 12000)」の下段=下限だった。
   #   4区画すべてで一致するので読み違いではない。
   jp='横田進入管制区', n='YOKOTA ACA', eff_note='図に上限の記載なし',
   outer=[1,2,3,4,5,10,11,12,17,19,20,21,22,9,6],
   sub=[
     dict(n='FL230', lo=23000, ring=[1,2,3,4,5,6]),
     dict(n='FL180', lo=18000, ring=[5,6,9,8,7]),
     dict(n='FL160', lo=16000, ring=[5,7,13,14,12,11,10]),
     dict(n='12000', lo=12000, ring=[7,8,16,15,14,13]),
     # ⚠ (19)→(17)→(18) と回る。(17)を飛ばすと三角形(17)(18)(19)が抜ける
     dict(n='8000',  lo=8000,  ring=[8,9,22,21,20,19,17,18,15,16]),
     dict(n='FL140', lo=14000, ring=[14,15,18,17,12]),
   ]),
}


RJAK_ARP = (36.03472, 140.19278)      # 霞ヶ浦飛行場ARP(3000区画の5NM弧の中心)
TK15 = (36.4897, 139.8633)            # 362923N/1395148E(左上の15NM弧の中心)

SPEC['RJTT/ACA'] = dict(
   jp='東京進入管制区', n='TOKYO ACA', eff_note='',
   outer=[7,6,42,47,55,54,48,39,17,18,16,5,4,3,2,15,14,58,57,56,59,8],
   sub=[
     dict(n='FL230', up=23000, ring=[1,2,3,4,5]),
     dict(n='FL180', up=24000, lo=18000, ring=[59,8,50,56]),
     dict(n='12000', up=24000, lo=12000, ring=[56,50,51,52,58,57]),
     dict(n='8000(西)', up=24000, lo=8000, ring=[50,8,9,10,11,12,13,53,52,51]),
     dict(n='FL140', up=24000, lo=14000, ring=[58,52,53,13,14]),
     # 左上は 15NM弧で切られた (7) の楔
     dict(n='4000(北西)', up=24000, lo=4000, ring=[
        7, {'cut':TK15,'r':15,'seg':(7,6)},
        {'arc':TK15,'r':15,'from':{'seg':(7,6)},'to':{'seg':(7,8)}},
        {'cut':TK15,'r':15,'seg':(7,8)}]),
     dict(n='7000', up=24000, lo=7000, ring=[6,42,46,45,44,43,41,35,36,29]),
     dict(n='10000', up=24000, lo=10000, ring=[46,47,55,54,48,49,43,44,45]),
     # ⚠ 8000(EXC 8000)のラベルは引き出し線が2本あり、離れた2区画を指す
     dict(n='8000(東A)', up=24000, lo=8000, ring=[43,49,48,39,40,41]),
     dict(n='8000(東B)', up=24000, lo=8000, ring=[39,17,19,20]),
     dict(n='6000', up=24000, lo=6000, ring=[37,40,39,20,21,38]),
     dict(n='4000(東)', up=24000, lo=4000, ring=[37,38,21,22,23]),
     dict(n='5000', up=24000, lo=5000, ring=[33,37,23,30]),
     dict(n='2500', up=24000, lo=2500, ring=[30,23,24,25]),
     dict(n='1800', up=24000, lo=1800, ring=[26,27,30,25]),
     # 3000は霞ヶ浦ARPから5NMの弧。(28)と(32)は弧の上、(31)は弧の外
     dict(n='3000', up=24000, lo=3000, ring=[
        {'arc':RJAK_ARP,'r':5,'from':28,'to':32}, 31, 27, 26]),
     dict(n='4000(中央)', up=24000, lo=4000, ring=[29,36,35,34,31,32,28]),
   ],
   # 残り(外形から上の区画を引いたもの)。下限の記載が無い「FL240」の区域。
   # ⚠ (35)(41)(40)(37)(33)(34)で囲まれるセルと、(46)(47)(55)の小片(13000)も
   #   ここに含まれる。前者はラベルが見当たらず、後者は4.7km²しかない。
   #   どちらも「下限の記載なし」として出すのが安全側
   remainder=dict(n='FL240', up=24000),
)


# 百里ACA。⚠ **33/42点が東京ACAと同一座標**で、南西の区画は東京ACAと同じもの。
# 重複は最後の突合で自動的に落ちる(上下限が揃っている東京側を残す)。
# 図の数値は**下限**(東京の図で同じ区画が「FL240 / nnnn (EXC nnnn)」の下段)。
NRE49 = (35.7834, 140.3599)   # 「NRE 49NM」弧の中心。(33)(34)から各49NMで、
                              # 弧が北へ膨らむ側から選んだ(成田の北西2km付近)
RJAK5 = (36.03472, 140.19278) # 霞ヶ浦ARP(5NM弧)

SPEC['RJAH/ACA'] = dict(
   jp='百里進入管制区', n='HYAKURI ACA', eff_note='図に上限の記載なし',
   ctr=NRE49,
   outer=[23,36,35,39,41,40,30,31,19,17,15,6,5,3,2,11,10],
   sub=[
     dict(n='13000', lo=13000, ring=[36,35,39,38,37,34,{'arcp':(34,33)},33]),
     dict(n='10000', lo=10000, ring=[33,{'arcp':(33,34)},34,27,28,29,25,26]),
     dict(n='FL230', lo=23000, ring=[34,37,38,39,41,40,30,20,27]),
     dict(n='7000',  lo=7000,  ring=[23,22,33,26,25,29,24,13,14,10]),
     dict(n='8000(北)', lo=8000, ring=[29,28,27,20,21,24]),
     dict(n='8000(東)', lo=8000, ring=[20,30,31,19]),
     dict(n='6000',  lo=6000,  ring=[16,21,20,19,17,18]),
     dict(n='5000',  lo=5000,  ring=[9,16,6,4]),
     dict(n='4000(南)', lo=4000, ring=[16,18,17,15,6]),
     dict(n='2500',  lo=2500,  ring=[4,6,5,3]),
     dict(n='1800',  lo=1800,  ring=[2,1,4,3]),
     dict(n='3000',  lo=3000,  ring=[{'arcp':(11,8),'c':RJAK5},7,1,2]),
     dict(n='4000(北西)', lo=4000, ring=[10,14,13,12,7,8,11]),
   ],
   remainder=dict(n='(下限の記載なし)'),
)


def main():
    base = ad2_dir()
    if not base: print('AIPのAD2フォルダが見つかりません', file=sys.stderr); sys.exit(1)
    if '--annot' in sys.argv:
        i = sys.argv.index('--annot')
        k = sys.argv[i+3] if len(sys.argv) > i+3 else 'ACA'
        annotate(sys.argv[i+1], int(sys.argv[i+2]), base, k); return
    here = os.path.dirname(os.path.abspath(__file__))
    cache = os.path.join(here, 'aca_points.json')
    if '--cache' in sys.argv and os.path.exists(cache):
        P = json.load(open(cache))
    else:
        print('AD2のチャートから座標表を抽出中…')
        P = harvest(base)
        json.dump(P, open(cache, 'w'), ensure_ascii=False, indent=0, sort_keys=True)
    print(f'  {len(P)} チャート / {sum(len(v) for v in P.values())} 点 → tools/aca_points.json')
    for k in sorted(P): print(f'    {k:12}{len(P[k]):4}点')

    out, ng = [], 0
    for key, sp in SPEC.items():
        pts = {int(a): b for a, b in P.get(key, {}).items()}
        if not pts: print(f'  ⚠ {key} の座標表が無い', file=sys.stderr); ng += 1; continue
        ring = lambda r: build(r, pts, sp.get('ctr'))
        oa = sph_area(ring(sp['outer']))
        tot = sum(sph_area(ring(s['ring'])) for s in sp['sub'])
        rem = sp.get('remainder')
        icao, kind = key.split('/')
        if not rem:
            d = abs(tot - oa) / oa * 100
            print(f"  {key}: 副区画{len(sp['sub'])} 合計{tot:.1f} / 外形{oa:.1f} km² 差{d:.4f}%")
            if d > 0.01:
                print(f'  ⚠ {key} は区画の読み違い(合計が外形と一致しない)', file=sys.stderr)
                ng += 1; continue
        else:
            # 残りは外形から引いて作る。**区画同士が重なっていないこと**を
            # shapelyで確かめる(合計面積の一致だけでは、どこが違うか分からない)
            from shapely.geometry import Polygon
            from shapely.ops import unary_union
            K = math.cos(math.radians(pts[list(pts)[0]][0]))
            pl = lambda r: Polygon([(b*K, a) for a, b in ring(r)]).buffer(0)
            gs = [pl(s['ring']) for s in sp['sub']]
            ov = 0.0
            for i in range(len(gs)):
                for j in range(i+1, len(gs)):
                    ov = max(ov, gs[i].intersection(gs[j]).area * 111.32**2 / K)
            og = pl(sp['outer'])
            outside = unary_union(gs).difference(og).area * 111.32**2 / K
            print(f"  {key}: 副区画{len(sp['sub'])} 合計{tot:.1f}/外形{oa:.1f} km² "
                  f"最大重なり{ov:.1f} 外形はみ出し{outside:.1f} km²")
            if ov > 2.0 or outside > 2.0:
                print(f'  ⚠ {key} は区画の読み違い', file=sys.stderr); ng += 1; continue
            r = og.difference(unary_union(gs))
            parts = [r] if r.geom_type == 'Polygon' else list(r.geoms)
            parts = [q for q in parts if q.area * 111.32**2 / K > 1.0]
            print(f"    残り(下限記載なし) {sum(q.area for q in parts)*111.32**2/K:.0f} km² {len(parts)}片")
            for q in parts:
                out.append(dict(n=sp['n'] + ' ' + rem['n'], jp=sp['jp'], k=kind, icao=icao,
                                up=rem.get('up'), lo=rem.get('lo'), rmk=sp.get('eff_note', ''),
                                pts=[[round(y, 6), round(x/K, 6)] for x, y in q.exterior.coords]))
        for s2 in sp['sub']:
            out.append(dict(n=sp['n'] + ' ' + s2['n'], jp=sp['jp'], k=kind, icao=icao,
                            up=s2.get('up'), lo=s2.get('lo'), rmk=sp.get('eff_note', ''),
                            pts=ring(s2['ring'])))
    if ng: print(f'{ng} 件を検算落ちで除外', file=sys.stderr)

    # ── 図をまたいだ重複を落とす ────────────────────────────────
    # 隣り合う進入管制区は境界を共有していて、**同じ区画が複数の図に載る**
    # (百里ACAは42点中33点が東京ACAと同一座標、横田ACAは4区画が重なり100%)。
    # 二重に描かないよう、**上下限が揃っている図を優先**して先に置き、
    # 後の図はその差分だけを残す。⚠ 単純に捨てると、百里の7000のように
    # 東京より北へ広い版が丸ごと消える(東京の図はそこで切れているだけ)。
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    K0 = math.cos(math.radians(36.0))
    S0 = 111.32**2 / K0
    def _pg(f): return Polygon([(b*K0, a) for a, b in f['pts']]).buffer(0)
    score = lambda f: (f['up'] is not None) + (f['lo'] is not None)
    order = sorted(range(len(out)), key=lambda i: (-score(out[i]), -_pg(out[i]).area))
    keep, acc, drop, clip = [], None, 0, 0
    for i in order:
        g = _pg(out[i])
        if g.area <= 0: continue
        if acc is not None:
            left = g.difference(acc)
            if left.area < 0.05 * g.area:
                drop += 1; continue                    # ほぼ丸ごと重複
            if left.area < 0.999 * g.area:
                cut = (g.area - left.area) * S0
                print(f"  {out[i]['n']}: 既出と重なる {cut:.0f}km² を切り取り")
                g = left; clip += 1
        f = dict(out[i])
        parts = [g] if g.geom_type == 'Polygon' else list(g.geoms)
        for q in parts:
            if q.area * S0 < 1.0: continue
            r = dict(f); r['pts'] = [[round(y, 6), round(x/K0, 6)] for x, y in q.exterior.coords]
            keep.append(r)
        acc = q if acc is None else unary_union([acc, g])
        acc = unary_union([acc, g])
    if drop or clip: print(f'  重複: {drop} 件を除外 / {clip} 件を切り取り')
    out = keep

    dst = os.path.join(here, '..', 'aca.json')
    eff = os.path.basename(os.path.dirname(base))
    json.dump({'eff': eff, 'src': 'AIP Japan AD 2.17 添付チャート', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 区画 → aca.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')


if __name__ == '__main__': main()
