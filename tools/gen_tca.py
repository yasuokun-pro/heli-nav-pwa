#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東京ターミナルコントロールエリア 生成 (tools/tca_tokyo.gen.json)
================================================================
出典: AIP Japan **RJTT AD 2.17 添付図 "Tokyo Terminal Control Area"**

⚠ **この図だけ番号付きの座標表が無い**。他のACA/TCA図は (1)(2)… の頂点表を
  持つのでジオリファレンス不要だが、東京TCAは図中に座標が5点しかなく、
  形は「30NM FM RJTT ARP」のように**弧と方位線の名前**で描かれている。
  よって**図を読み取る**しかない。**出力は近似**で、アプリ側でもその旨を出す。

読み取りの手順
--------------
1. ジオリファレンス
   navaidのラベル位置(HUC/SYE/SHT/NRE/CVT/OJT/TET)でアフィンを当てる。
   ⚠ これだけだと残差8pt(≒1.2NM)で**足りない**。図に描かれている**CTR円を
     画像から探して**平行移動を補正すると一致する(霞ヶ浦CTR 5NMが一番濃く出る)。
   ⚠ インク量の最大化でアフィン6パラメータを全部動かすと**かえって悪化する**
2. 太線だけ残す (MaxFilter(5)→MinFilter(5))
   海岸線・文字・破線の注記・枠が消えて**空域の線だけ**になる
3. 塗り分け(scanline flood fill)で区画を切り出す
4. 高度ラベル(「10000」+下段の数字)は本文レイヤから位置が取れる。
   ⚠ **引き出し線で離れた区画を指すものが多い**ので、距離で機械的に割り当てると
     間違う(東京ACAの「8000」と同じ罠)。CELL に読み取り結果を手で書いてある
5. 区画の境界をMoore追跡 → shapelyで間引き → 緯度経度へ

⚠ **上限は全区画10000**。例外はハッチの3区画だけで、そこは**2段**になる
  (1800-2999 と 6001-10000 など)。凡例から読む
"""
import os, re, sys, glob, math, json, subprocess
import numpy as np

try:
    from PIL import Image, ImageFilter
    from shapely.geometry import Polygon
except ImportError:
    print('Pillow と shapely が要る', file=sys.stderr); sys.exit(1)

PAGE, DPI = 28, 300
NAV = {'HUC': (36.18701, 140.41373), 'SYE': (36.01093, 139.83917),
       'SHT': (35.80194, 140.00972), 'NRE': (35.78234, 140.36254),
       'CVT': (35.72668, 140.79991), 'OJT': (35.18414, 140.37143),
       'TET': (34.97083, 139.83806)}
LBL = {'HUC': (287.7, 116.4), 'SYE': (154.0, 184.9), 'SHT': (176.3, 257.8),
       'NRE': (282.5, 271.3), 'CVT': (392.2, 276.4), 'OJT': (291.0, 454.1),
       'TET': (154.8, 545.8)}
SHIFT = (42, 22)      # 描かれている霞ヶ浦CTR/成田CTRの円で実測した平行移動(px)

# 区画id → (上限, 下限)。⚠ **引き出し線を目視で追って決めた**。
#   id は本ファイルの塗り分けの順に決まるので、AIRAC更新で図が変わったら
#   probe(tools/tca_tokyo_probe.py)で振り直すこと
CELL = {
    4: (10000, 3000), 5: (10000, 3000), 6: (10000, 4000), 7: (10000, 5000),
    8: (10000, 2000), 9: (10000, 4000), 13: (10000, 1801), 16: (10000, 6001),
    18: (10000, 2501), 19: (10000, 1800), 21: (10000, 2000), 22: (10000, 3001),
    23: (10000, 1800), 24: (10000, 2500), 25: (10000, 6001), 26: (10000, 6000),
    27: (10000, 2500), 29: (10000, 2000), 30: (10000, 5001), 31: (10000, 4500),
    32: (10000, 4000), 33: (10000, 4001), 35: (10000, 3000), 36: (10000, 2000),
    37: (10000, 5001), 38: (10000, 6001), 39: (10000, 3000), 42: (10000, 4000),
}
# ハッチの3区画は**上下2段**。凡例から読む(上段/下段の順)
HATCH = {10: [(2999, 1800), (10000, 6001)],
         11: [(2999, 1801), (10000, 6001)],
         14: [(1999, 1801), (10000, 6001)]}
# 細い分割線が途切れていて1区画に融合するもの。太らせ量と、含まれるラベルの
# 位置(px)→高度。⚠ 成田南東の3本帯は「5001」の文字が分割線を切っている
SPLIT = {28: dict(dilate=11, parts=[((1316, 1272), (10000, 4001)),
                                    ((1381, 1319), (10000, 5001)),
                                    ((1434, 1431), (10000, 6001))])}
DROP = {43, 44, 45, 46}    # 図の下にある別枠(UTC限定図・周波数図)


def rjtt_pdf():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine/RJTT__*.pdf',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine/RJTT__*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: return f[-1]
    return None


def georef():
    S = DPI / 72.0; ks = list(NAV)
    A = np.array([[NAV[k][1], NAV[k][0], 1] for k in ks])
    cx = np.linalg.lstsq(A, np.array([LBL[k][0]*S for k in ks]), rcond=None)[0]
    cy = np.linalg.lstsq(A, np.array([LBL[k][1]*S for k in ks]), rcond=None)[0]
    cx[2] += SHIFT[0]; cy[2] += SHIFT[1]
    M = np.array([[cx[0], cx[1]], [cy[0], cy[1]]])
    Mi = np.linalg.inv(M)
    def px2ll(x, y):
        lon, lat = Mi @ np.array([x-cx[2], y-cy[2]])
        return round(float(lat), 5), round(float(lon), 5)
    return px2ll, (cx, cy)


def scanfill(state, sy, sx, val):
    H, W = state.shape; st = [(sy, sx)]; n = 0
    while st:
        y, x = st.pop()
        if state[y, x] != 0: continue
        x0 = x
        while x0 > 0 and state[y, x0-1] == 0: x0 -= 1
        x1 = x
        while x1 < W-1 and state[y, x1+1] == 0: x1 += 1
        state[y, x0:x1+1] = val; n += x1-x0+1
        for yy in (y-1, y+1):
            if not (0 <= yy < H): continue
            idx = np.where(state[yy, x0:x1+1] == 0)[0]
            if not len(idx): continue
            br = np.where(np.diff(idx) > 1)[0]
            for s in [idx[0]] + [idx[i+1] for i in br]:
                st.append((yy, x0+int(s)))
    return n


def segment(line):
    lab = np.zeros(line.shape, dtype=np.int32); lab[line] = -1
    scanfill(lab, 3, 3, -2)
    cells, cid = [], 1
    while True:
        ys, xs = np.where(lab == 0)
        if not len(ys): break
        n = scanfill(lab, int(ys[0]), int(xs[0]), cid)
        cells.append((cid, n)); cid += 1
        if cid > 400: break
    return lab, cells


def dilate(mask, k):
    return np.array(Image.fromarray(np.where(mask, 0, 255).astype('uint8'))
                    .filter(ImageFilter.MinFilter(k))) < 128


def trace(mask):
    """Moore近傍で外周を1周する(戻りは (x,y) の列)。
       ⚠ 開始画素の探索方向と backtrack の更新を間違えると2〜4点で止まる"""
    H, W = mask.shape
    ys, xs = np.where(mask)
    i0 = int(np.argmin(ys.astype(np.int64)*W + xs))
    s = (int(ys[i0]), int(xs[i0]))
    NB = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]  # 東から時計回り
    cur, bdir = s, 4                       # 西から来たことにする
    out = [(s[1], s[0])]
    for _ in range(600000):
        nxt = None
        for j in range(1, 9):
            k = (bdir + j) % 8
            y, x = cur[0]+NB[k][0], cur[1]+NB[k][1]
            if 0 <= y < H and 0 <= x < W and mask[y, x]:
                nxt = (k, (y, x)); break
        if nxt is None: break
        k, cur = nxt
        bdir = (k + 4) % 8
        out.append((cur[1], cur[0]))
        if cur == s and len(out) > 4: break
    return out


def main():
    pdf = rjtt_pdf()
    if not pdf: print('RJTTのPDFが見つからない', file=sys.stderr); sys.exit(1)
    subprocess.run(['pdftoppm', '-png', '-r', str(DPI), '-f', str(PAGE), '-l', str(PAGE),
                    pdf, '/tmp/tca_tt'], check=True)
    img = Image.open(sorted(glob.glob('/tmp/tca_tt-*.png'))[-1]).convert('L')
    er = img.filter(ImageFilter.MaxFilter(5))
    thick = np.array(Image.fromarray(np.where(np.array(er) < 128, 0, 255).astype('uint8'))
                     .filter(ImageFilter.MinFilter(5))) < 128
    # ⚠ **1px太らせてから塗り分ける**。線の途切れで隣の区画へ漏れるのを防ぐ。
    #   CELL の区画idはこの手順での塗り分け順に対応しているので変えないこと
    thick = dilate(thick, 3)
    lab, cells = segment(thick)
    px2ll, _ = georef()

    def emit(mask, up, lo, name, out):
        m = dilate(mask, 9)          # 線幅の半分(≒4px)ぶん戻して隣と接するように
        pts = trace(m)
        if len(pts) < 20:
            print(f'  ⚠ {name}: 外周が短すぎる({len(pts)}点)', file=sys.stderr); return
        g = Polygon(pts).buffer(0).simplify(4.0)
        if g.is_empty:
            print(f'  ⚠ {name}: 図形が空', file=sys.stderr); return
        if g.geom_type != 'Polygon': g = max(g.geoms, key=lambda q: q.area)
        ring = [px2ll(x, y) for x, y in g.exterior.coords]
        out.append(dict(n=name, up=up, lo=lo, pts=[[a, b] for a, b in ring]))

    out = []
    print(f'  塗り分け {len([c for c in cells if c[1]>=800])} 区画')
    for cid, n in cells:
        if n < 800 or cid in DROP: continue
        mask = lab == cid
        if cid in SPLIT:
            sp = SPLIT[cid]
            dl = dilate(thick, sp['dilate'])
            st = np.zeros(lab.shape, dtype=np.int32); st[~mask] = -1; st[mask & dl] = -1
            k = 1
            while True:
                ys, xs = np.where(st == 0)
                if not len(ys): break
                scanfill(st, int(ys[0]), int(xs[0]), k); k += 1
                if k > 60: break
            # 太らせで削れた分を、一番近い小区画へ広げる
            own = st.copy()
            for _ in range(sp['dilate']+4):
                grow = dilate(own > 0, 3)
                todo = mask & (own <= 0) & grow
                if not todo.any(): break
                yy, xx = np.where(todo)
                for y, x in zip(yy, xx):
                    w = own[max(0, y-2):y+3, max(0, x-2):x+3]
                    v = [int(t) for t in np.unique(w) if t > 0]
                    if v: own[y, x] = v[0]
            for (lx, ly), (up, lo) in sp['parts']:
                sid = int(own[ly, lx])
                if sid <= 0: print(f'  ⚠ 区画{cid} の分割に失敗', file=sys.stderr); continue
                emit(own == sid, up, lo, f'{up}/{lo}', out)
            continue
        if cid in HATCH:
            for up, lo in HATCH[cid]: emit(mask, up, lo, f'{up}/{lo}', out)
            continue
        if cid not in CELL:
            print(f'  ⚠ 区画{cid}({n}px) に高度の割り当てが無い', file=sys.stderr); continue
        up, lo = CELL[cid]
        emit(mask, up, lo, f'{up}/{lo}', out)

    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, 'tca_tokyo.gen.json')
    eff = os.path.basename(os.path.dirname(os.path.dirname(pdf)))
    json.dump({'eff': eff, 'src': 'AIP Japan RJTT AD 2.17 添付図(図の読み取り・近似)',
               'f': out}, open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 区画 → {os.path.basename(dst)} ({os.path.getsize(dst)/1024:.0f}KB)')
    lo = sorted({f['lo'] for f in out})
    print(f'  下限の種類: {lo}')


# ══════════════════════════════════════════════════════════
# 百里ターミナルコントロールエリア (RJAH AD 2.17 添付図)
# ══════════════════════════════════════════════════════════
# ⚠ **公表座標だけでは組めない**。同心円弧(5/6/9/12/14.8/19/24/30NM)と
#   放射線(003/033/043/253/293/323°T)で組まれているが、**どの中心を使っても
#   公称半径に合わない**(ARP/HUC VOR/当てはめのいずれもRMS 0.24〜0.38NM、
#   最大0.5〜0.6NM)。さらに27区画の角の多くが座標表(30点)に無い。
#   よって東京TCAと同じく**図の読み取り**で起こす。出力は近似。
# 図の作りは東京TCAより素直:
#   * **各区画に丸数字①〜㉗が振ってあり、凡例に上下限の表がある**(引き出し線なし)
#   * 地図の下敷きが無い純粋な模式図なので、**生インクをそのまま塗り分けられる**
# ⚠ 丸数字は「033°T」等の回転文字の断片(03/3/4/5)と紛らわしい。
#   **数字のまわりに丸があるか**(半径10〜19pxのリング上のインク率>0.85)で判別する
# ⚠ ①②⑩⑭⑰ は**丸数字が区画の外**に置かれていて短い引き出し線で指している。
#   半径を広げながら探し、**候補を順位付けして全部が別区画になるように割り当てる**
HY_PAGE = 10
HY_SHIFT = (2, -6)     # 図の灰色CTZ円(RJAH ARPから5NM)を画像から探して実測した補正


def _circled(bbox_html, ink, S):
    """丸数字(1〜27)の位置を返す。回転文字の断片を丸の有無で弾く"""
    H, W = ink.shape
    out = []
    for x0, y0, x1, y1, t in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>',
            bbox_html):
        t = t.strip()
        if not re.fullmatch(r'\d{1,2}', t): continue
        v = int(t)
        if not (1 <= v <= 27): continue
        if float(x0) > 415 and float(y0) < 460: continue        # 凡例の列
        cx, cy = (float(x0)+float(x1))/2*S, (float(y0)+float(y1))/2*S
        best = 0
        for r in range(10, 20):
            n = hit = 0
            for i in range(72):
                a = i*5*math.pi/180
                x, y = int(cx+r*math.cos(a)), int(cy+r*math.sin(a))
                if 0 <= x < W and 0 <= y < H:
                    n += 1; hit += ink[y-1:y+2, x-1:x+2].any()
            best = max(best, hit/max(n, 1))
        if best > 0.85: out.append((v, cx, cy))
    return out


def _legend(bbox_html):
    """凡例の「丸数字 上限/下限」を読む"""
    W = [(float(a), float(b), float(c), float(d), t.strip()) for a, b, c, d, t in
         re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>',
                    bbox_html)]
    leg = [w for w in W if w[0] > 415 and w[1] < 460]
    nums = [w for w in leg if re.fullmatch(r'\d{1,2}', w[4])]
    vals = [w for w in leg if re.fullmatch(r'\d{4,5}', w[4])]
    out = {}
    for x0, y0, x1, y1, t in nums:
        yc = (y0+y1)/2
        col = [v for v in vals if x1 < v[0] < x1+30]
        up = sorted([v for v in col if (v[1]+v[3])/2 < yc], key=lambda v: abs((v[1]+v[3])/2-yc))
        lo = sorted([v for v in col if (v[1]+v[3])/2 > yc], key=lambda v: abs((v[1]+v[3])/2-yc))
        if up and lo: out[int(t)] = (int(up[0][4]), int(lo[0][4]))
    return out


def hyakuri():
    import json as _json
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine/RJAH__*.pdf',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine/RJAH__*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: pdf = f[-1]; break
    else:
        print('RJAHのPDFが無い', file=sys.stderr); return None
    subprocess.run(['pdftoppm', '-png', '-r', str(DPI), '-f', str(HY_PAGE), '-l', str(HY_PAGE),
                    pdf, '/tmp/tca_ah'], check=True)
    subprocess.run(['pdftotext', '-bbox-layout', '-f', str(HY_PAGE), '-l', str(HY_PAGE),
                    pdf, '/tmp/tca_ah.html'], check=True)
    img = Image.open(sorted(glob.glob('/tmp/tca_ah-*.png'))[-1]).convert('L')
    ink = np.array(img) < 150
    H, W = ink.shape; S = DPI/72.0
    bb = open('/tmp/tca_ah.html').read()

    here = os.path.dirname(os.path.abspath(__file__))
    P = {int(k): v for k, v in
         _json.load(open(os.path.join(here, 'aca_points.json')))['RJAH/TCA'].items()}
    lab = {}
    for x0, y0, x1, y1, t in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', bb):
        m = re.fullmatch(r'\((\d{1,2})\)', t.strip())
        if not m: continue
        y = (float(y0)+float(y1))/2
        if y > 560: continue                     # 下の座標一覧は図ではない
        lab.setdefault(int(m.group(1)), ((float(x0)+float(x1))/2, y))
    ks = [k for k in lab if k in P]
    A = np.array([[P[k][1], P[k][0], 1] for k in ks])
    cx = np.linalg.lstsq(A, np.array([lab[k][0]*S for k in ks]), rcond=None)[0]
    cy = np.linalg.lstsq(A, np.array([lab[k][1]*S for k in ks]), rcond=None)[0]
    cx[2] += HY_SHIFT[0]; cy[2] += HY_SHIFT[1]
    M = np.linalg.inv(np.array([[cx[0], cx[1]], [cy[0], cy[1]]]))
    def px2ll(x, y):
        lon, lat = M @ np.array([x-cx[2], y-cy[2]])
        return round(float(lat), 5), round(float(lon), 5)

    lb, cells = segment(ink)
    sz = {int(i): int((lb == i).sum()) for i in np.unique(lb) if i > 0}
    OUTSIDE = max(sz, key=lambda k: sz[k])       # 枠内・TCA外の広い領域
    nums = _circled(bb, ink, S)
    rank = {}
    for v, ux, uy in nums:
        order = []
        for r in range(22, 200, 3):
            c = {}
            for i in range(144):
                a = i*2.5*math.pi/180
                x, y = int(ux+r*math.cos(a)), int(uy+r*math.sin(a))
                if 0 <= x < W and 0 <= y < H:
                    u = int(lb[y, x])
                    if u > 0 and u != OUTSIDE and sz[u] >= 600: c[u] = c.get(u, 0)+1
            for u in sorted(c, key=lambda z: -c[z]):
                if u not in order: order.append(u)
            if len(order) >= 4: break
        rank[v] = order
    used, cellof = set(), {}
    for v in sorted(rank, key=lambda k: len(rank[k])):
        for u in rank[v]:
            if u not in used: cellof[v] = u; used.add(u); break
    leg = _legend(bb)
    miss = [v for v in range(1, 28) if v not in cellof or v not in leg]
    if miss: print(f'  ⚠ 百里TCA: 対応が取れない丸数字 {miss}', file=sys.stderr)
    out = []
    for v in sorted(cellof):
        if v not in leg: continue
        up, lo = leg[v]
        m = dilate(lb == cellof[v], 9)
        pts = trace(m)
        if len(pts) < 20: print(f'  ⚠ ㉔{v}: 外周が取れない', file=sys.stderr); continue
        g = Polygon(pts).buffer(0).simplify(4.0)
        if g.is_empty: continue
        if g.geom_type != 'Polygon': g = max(g.geoms, key=lambda q: q.area)
        out.append(dict(n=f'{up}/{lo}', up=up, lo=lo,
                        pts=[[a, b] for a, b in (px2ll(x, y) for x, y in g.exterior.coords)]))
    dst = os.path.join(here, 'tca_hyakuri.gen.json')
    eff = os.path.basename(os.path.dirname(os.path.dirname(pdf)))
    _json.dump({'eff': eff, 'src': 'AIP Japan RJAH AD 2.17 添付図(図の読み取り・近似)',
                'f': out}, open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 区画 → tca_hyakuri.gen.json ({os.path.getsize(dst)/1024:.0f}KB)')
    return out


# ── 築城TCA(RJFZ AD 2.17 の2枚目) ─────────────────────────────
# ⚠ この図も**座標表が無い**。ただし東京・百里と違って構造が完全に規則的で、
#   **TQT(築城TACAN)を中心とする同心円弧12本と放射線**だけで組まれている。
#   弧の半径は 5/9/13/14/16/18/20/22/23/25/27/30NM で、画像から実測すると
#   9.00 13.01 14.09 15.98 18.02 20.06 21.98 23.02 25.04 27.07 30.00 と出る。
# ⚠ **方位は磁針方位**(図の上=磁北)。根拠は2つ:
#   ・図中の破線「DGC155°T」(真方位155°)が画面方位162.5°に描かれている(+7.5°)
#   ・DGCの記号が画面方位276.25°/32.35NM。真方位は268.70°/32.29NMなので
#     距離はぴったり、方位だけ+7.55°ずれる
#   AIPのMAG VAR実測値から作った推定式でも築城は7.63°W。VAR=7.6 を使う。
# ⚠ 小月CTR・北九州CTR・山口宇部情報圏の**真上の区画**(下限5001/3001)は
#   TQT中心ではなく各CTRの円で切られている。公称半径への寄せは
#   **接線方向のときだけ**にしないと、これらの円が壊れる。
# ⚠ SWEの記号でR-360の線が途切れていて、そのままだと塗り分けが漏れる。
#   放射線に沿って短い切れ目を探して橋渡ししてから塗り分ける。
TSU_PAGE = 7
TQT = (33.688228, 131.035825)     # RJFZ AD 2.19 334117.62N/1310208.97E
TSU_VAR = 7.6                     # 西偏(磁針方位→真方位)
TSU_RAD = [5, 9, 13, 14, 16, 18, 20, 22, 23, 25, 27, 30]
TSU_THE = [0, 10, 40, 50, 55, 95, 110, 135, 165, 181, 225, 250, 265, 280]
# (代表点の半径NM, 代表点の磁針方位, 上限, 下限)。
# ⚠ 区画idは塗り分け順で決まって当てにならないので、**区画の中の1点**で引く。
#   代表点は各区画の「一番奥」(距離変換の最大点)なので多少図が変わっても当たる。
TSU_CELL = [
 (27.62,  23.2, 10000, 5000), (22.33,   9.8, 10000, 5001),   # 小月CTRの上
 (21.49, 355.2,  9000, 6000), (21.20,  32.9, 10000, 4000),
 (19.63, 345.2,  7000, 5000), (12.81, 349.2, 10000, 4500),   # 凡例(1)
 (15.95,   4.4, 10000, 2000), (12.81, 315.0,  7000, 4500),
 (26.31,  84.3, 10000, 3000), (13.60,  76.4, 10000, 1500),
 (16.26,  46.5, 10000, 3001),                                # 山口宇部情報圏の上
 ( 9.91,  13.5, 10000, 3001),                                # 北九州CTRの上
 ( 6.63, 302.7, 10000, 3500),                                # 凡例(2)
 ( 0.32,  45.3, 10000, 6001),                                # 築城CTRの上
 ( 9.77, 283.1,  6000, 4500), (14.59, 271.2,  6000, 4500),   # 後者が凡例(3)
 (10.79, 265.4,  6000, 3000),                                # 凡例(4)
 ( 5.27, 254.9,  6000, 3500), (19.57, 121.2, 10000, 4000),
 ( 7.29, 236.9, 10000, 3500),                                # 凡例(5)
 (10.45, 245.9, 10000, 3000), ( 9.57, 193.2, 10000, 5000),
 (15.57, 229.9, 10000, 6000), (16.65, 216.3, 10000, 8000),
 (17.49, 173.6, 10000, 8000), (17.34, 188.4,  9000, 8000),
 (26.00, 156.1, 10000, 7000), (23.89, 173.5, 10000, 9000),
]


def _tsu_dest(r_nm, brg_mag):
    """TQTから 磁針方位brg・r_nmNM の点"""
    la = math.radians(TQT[0]); dr = r_nm*1852/6371008.8
    br = math.radians(brg_mag - TSU_VAR)
    la2 = math.asin(math.sin(la)*math.cos(dr)+math.cos(la)*math.sin(dr)*math.cos(br))
    lo2 = math.radians(TQT[1]) + math.atan2(math.sin(br)*math.sin(dr)*math.cos(la),
                                            math.cos(dr)-math.sin(la)*math.sin(la2))
    return [round(math.degrees(la2), 6), round(math.degrees(lo2), 6)]


def tsuiki():
    import json as _json
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine/RJFZ__*.pdf',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine/RJFZ__*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: pdf = f[-1]; break
    else:
        print('RJFZのPDFが無い', file=sys.stderr); return None
    subprocess.run(['pdftoppm', '-png', '-r', str(DPI), '-f', str(TSU_PAGE), '-l', str(TSU_PAGE),
                    pdf, '/tmp/tca_fz'], check=True)
    img = Image.open(sorted(glob.glob('/tmp/tca_fz-*.png'))[-1]).convert('L')
    th = np.array(img.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))) < 150
    th[:250, :] = False; th[2600:, :] = False; th[:, :340] = False; th[:, 2200:] = False
    ys, xs = np.nonzero(th)

    def score(cx, cy):
        d = np.hypot(xs-cx, ys-cy)
        h, _ = np.histogram(d, bins=np.arange(0, 1200, 2))
        return float((h.astype(float)**2).sum())
    best = max(((score(x, y), x, y) for x in range(950, 1250, 10)
                for y in range(1000, 1350, 10)))
    _, cx, cy = best
    for st in (4, 2, 1):
        _, cx, cy = max((score(x, y), x, y) for x in range(cx-6*st, cx+6*st+1, st)
                        for y in range(cy-6*st, cy+6*st+1, st))
    d = np.hypot(xs-cx, ys-cy); m = (d > 615) & (d < 640)
    X, Y = xs[m].astype(float), ys[m].astype(float)
    c = np.linalg.lstsq(np.stack([X, Y, np.ones(len(X))], 1), X*X+Y*Y, rcond=None)[0]
    CX, CY = c[0]/2, c[1]/2
    S = math.sqrt(c[2]+CX*CX+CY*CY)/30.0
    print(f'  築城TCA: 中心({CX:.1f},{CY:.1f}) 30NM円から {S:.3f}px/NM')

    # 放射線の途中にある短い切れ目(navaidの記号)を橋渡しする
    fix = 0
    for t in TSU_THE:
        st, ct = math.sin(math.radians(t)), math.cos(math.radians(t))
        run = np.array([th[int(round(CY-i*ct)), int(round(CX+i*st))]
                        for i in range(int(S), int(30*S))])
        i = 0
        while i < len(run):
            if not run[i]:
                j = i
                while j < len(run) and not run[j]: j += 1
                if i > 15 and j < len(run)-15 and (j-i) < 45 \
                        and run[i-15:i].all() and run[j:j+15].all():
                    for k in range(i-2, j+2):
                        px = int(round(CX+(k+int(S))*st)); py = int(round(CY-(k+int(S))*ct))
                        th[py-5:py+6, px-5:px+6] = True
                    fix += 1
                i = j
            i += 1
    lb, cells = segment(th)
    print(f'  築城TCA: 切れ目{fix}箇所を橋渡し / {len([c for c in cells if c[1] > 200])}区画')

    out, used = [], set()
    for pr, pt, up, lo in TSU_CELL:
        x = CX + pr*S*math.sin(math.radians(pt)); y = CY - pr*S*math.cos(math.radians(pt))
        cid = int(lb[int(round(y)), int(round(x))])
        if cid <= 0 or cid in used:
            print(f'  ⚠ 築城TCA: 代表点({pr},{pt})が区画に当たらない', file=sys.stderr); continue
        used.add(cid)
        # 線の中心まで太らせてから追跡する(区画同士に隙間ができないように)
        pts = trace(dilate(lb == cid, 11))
        if len(pts) < 20:
            print(f'  ⚠ 築城TCA: 外周が取れない({pr},{pt})', file=sys.stderr); continue
        q = Polygon(pts).buffer(0).simplify(2.5)
        if q.geom_type != 'Polygon': q = max(q.geoms, key=lambda z: z.area)
        C = list(q.exterior.coords)[:-1]; n = len(C); P = []
        for i, (px, py) in enumerate(C):
            r = math.hypot(px-CX, py-CY)/S
            t = math.degrees(math.atan2(px-CX, -(py-CY))) % 360
            ax, ay = C[(i-1) % n]; bx, by = C[(i+1) % n]
            vx, vy = bx-ax, by-ay; L = math.hypot(vx, vy) or 1
            ux, uy = (px-CX)/(r*S or 1), (py-CY)/(r*S or 1)
            if abs(vx/L*ux + vy/L*uy) < 0.30:      # 接線方向のときだけ公称半径に寄せる
                b = min(TSU_RAD, key=lambda v: abs(v-r))
                if abs(b-r) < 0.35: r = b
            P.append(_tsu_dest(r, t))
        out.append(dict(n=f'{up}/{lo}', up=up, lo=lo, pts=P))
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, 'tca_tsuiki.gen.json')
    eff = os.path.basename(os.path.dirname(os.path.dirname(pdf)))
    _json.dump({'eff': eff, 'src': 'AIP Japan RJFZ AD 2.17 添付図(図の読み取り・近似)',
                'f': out}, open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 区画 → tca_tsuiki.gen.json ({os.path.getsize(dst)/1024:.0f}KB)')
    return out


if __name__ == '__main__':
    main()
    hyakuri()
    tsuiki()
