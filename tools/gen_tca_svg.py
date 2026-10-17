#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TCA(ターミナルコントロールエリア)を AD 2.17 の添付図の**線(ベクタ)**から起こす → aca.json の TCA に足す
=========================================================================================================
対象: 千歳・三沢・仙台・松島・小松・浜松・中部・関西・鹿児島(東京・百里・築城・福岡・那覇は gen_tca.py)
・図に座標の表は無く、「◯◯ から n NM の円弧」と放射線で区画を組んでいる。図は**縮尺どおり**(仙台: CTZ 5NM と外周 30NM の
  半径の比が一致)なので、図の線をそのまま地図の座標に移す:
  1) pdftocairo -svg で図のページの線を取り出す
  2) 外周の太い円弧(既知の半径 ref_r_nm)に円を当てはめて、中心(=基準の navaid)と縮尺(pt/NM)を決める
  3) 線を NM の平面に移して shapely で面に分け(polygonize)、外周の内側の面を区画にする
  4) 「10000 / 4500」の文字(pdftotext -bbox)の位置で区画に上限・下限を割り当てる
  5) 地図の座標へは基準の navaid から方位・距離で(大圏)
⚠ 図の上が真北か磁北かは図ごとに確かめる(cfg の rot = 図の上の真方位。磁北なら −偏差)。AIXM の ACA・CTR と重ねて検算する
使い方: python3 tools/gen_tca_svg.py RJSS [--airac 20261001] [--write]
"""
import os, re, sys, json, glob, math, subprocess
import numpy as np
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
from shapely.ops import unary_union, polygonize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
AIP = os.path.join(ROOT, 'aip', '1_AIP (PDF)')
R_NM = 3440.065

CFG = {
    'RJSS': {'name': 'SENDAI TCA', 'jp': '仙台ターミナルコントロールエリア', 'center': (38.13857, 140.92148), 'center_id': 'SDE',
             'ref_r_nm': 30, 'rot': -6,
             # 回転: 図の「180°」の放射線(SDE のラジアル・局の偏差 8°W → 真方位 172°)が図上で 177.9° に描かれている → 図の上は −6°。
             #   進入管制区(AIXM)・東北12/13-4(AIXM)の破線と重ねた当てはめも −6° が最良(中央値 0.37NM)
             },
    'RJSM': {'name': 'MISAWA TCA', 'jp': '三沢ターミナルコントロールエリア', 'center': (40.70382, 141.38111), 'center_id': 'MIS',
             'ref_r_nm': 30, 'rot': -8,
             # 回転: MIS の放射線 130°・245°・300°・325° が図上でもその角度(磁北が上)→ 局の偏差 8°W で −8°
             },
    'RJST': {'name': 'MATSUSHIMA TCA', 'jp': '松島ターミナルコントロールエリア', 'center': (38.403889, 141.225556), 'center_id': 'MXT',
             'ref_r_nm': 30, 'rot': -8, 'spec': 'spec_rjst',
             # ⚠ 図は模式図で、線の向きが場所ごとに違う(007°T の線は 014°・113°T の線は 116°・290° の放射線は 280° に描かれている)。
             #   図の線を写すと南側で 2〜3NM ずれるので、図に書かれた定義から幾何で組む(spec_rjst)。図は区画の並びと高度の確認にだけ使う
             },
    'RJNK': {'name': 'KOMATSU TCA', 'jp': '小松ターミナルコントロールエリア', 'center': (36.39649, 136.40514), 'center_id': 'KMC',
             'ref_r_nm': 30, 'rot': -8, 'spec': 'spec_rjnk'},
    'RJNH': {'name': 'HAMAMATSU TCA', 'jp': '浜松ターミナルコントロールエリア', 'center': (34.74735, 137.71006), 'center_id': 'LHT',
             'ref_r_nm': 20, 'rot': 0, 'spec': 'spec_rjnh'},
    'RJFK': {'name': 'KAGOSHIMA TCA', 'jp': '鹿児島ターミナルコントロールエリア', 'center': (31.803333, 130.719444), 'center_id': 'RJFK ARP',
             'ref_r_nm': 40, 'rot': 0,
             # 地図の上に縮尺どおり(3.4pt/NM・真北が上)に描かれている。CTR の円(鹿児島・宮崎・新田原)の中心で位置合わせ
             'anchors': [((239.4, 395.1), (31.803333, 130.719444)), ((365.8, 378.0), (31.877222, 131.448611)),
                         ((365.8, 336.6), (32.083611, 131.451389))], 'eps': 0.25,
             'lead_min': 4,           # 縮尺が小さく引き出し線が短い(鹿児島 CTR の 10000/3001 は 11pt)
             'lead_w': 0.45},         # 引き出し線は 0.29〜0.39pt。区画の線(0.49pt)の端が文字の近くに来る(宮崎 CTR の 193°T)
}


def dest(lat, lng, brg, nm):
    d, b, p1, l1 = nm / R_NM, math.radians(brg), math.radians(lat), math.radians(lng)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return [round(math.degrees(p2), 6), round(math.degrees(l2), 6)]


def svg_paths(svg):
    """線幅・破線の有無つきでストロークのパスを座標列(pt・y 下向き)で取り出す"""
    num = re.compile(r'[-+]?\d*\.?\d+(?:e-?\d+)?')
    out = []
    for m in re.finditer(r'<path ([^>]*?)/>', svg, re.S):
        at = m.group(1)
        sw = re.search(r'stroke-width="([\d.]+)"', at); d = re.search(r'\sd="([^"]*)"', ' ' + at)
        if not sw or not d or 'fill="none"' not in at: continue
        tr = re.search(r'transform="matrix\(([^)]*)\)"', at)
        a, b, c, dd, e, f = [float(x) for x in num.findall(tr.group(1))] if tr else (1, 0, 0, 1, 0, 0)
        subs, cur, pos, curve = [], [], (0.0, 0.0), False
        runs, run = [], []          # 連続した C(円弧)の区間ごとの点列。直線と円弧が1本のパスにつながっていても円を当てはめられるように
        for op, arg in re.findall(r'([MLCZ])([^MLCZ]*)', d.group(1)):
            if op != 'C' and len(run) > 4: runs.append(run)
            if op != 'C': run = []
            v = [float(x) for x in num.findall(arg)]
            if op == 'M':
                if len(cur) > 1: subs.append((cur, curve))
                cur = [(v[0], v[1])]; pos = (v[0], v[1]); curve = False
                for i in range(2, len(v), 2): cur.append((v[i], v[i + 1])); pos = (v[i], v[i + 1])
            elif op == 'L':
                for i in range(0, len(v), 2): cur.append((v[i], v[i + 1])); pos = (v[i], v[i + 1])
            elif op == 'C':
                curve = True
                if not run: run = [pos]
                for i in range(0, len(v), 6):
                    p0, p1, p2, p3 = pos, (v[i], v[i + 1]), (v[i + 2], v[i + 3]), (v[i + 4], v[i + 5])
                    run.append(((p0[0] + 3 * p1[0] + 3 * p2[0] + p3[0]) / 8, (p0[1] + 3 * p1[1] + 3 * p2[1] + p3[1]) / 8))   # t=0.5 も弧の上
                    run.append(p3)
                    for k in range(1, 17):
                        t = k / 16.0; u = 1 - t
                        cur.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
                    pos = p3
            elif op == 'Z':
                if len(cur) > 1: cur.append(cur[0]); subs.append((cur, curve))
                cur = []
        if len(cur) > 1: subs.append((cur, curve))
        if len(run) > 4: runs.append(run)
        T = lambda q: [(a * x + c * y + e, b * x + dd * y + f) for x, y in q]
        for k, (sub, cv) in enumerate(subs):
            out.append({'w': float(sw.group(1)), 'dash': 'stroke-dasharray' in at, 'curve': cv, 'pts': T(sub),
                        'runs': [T(r) for r in runs] if k == 0 else []})
    return out


def fitc(P):
    P = np.array(P); x, y = P[:, 0], P[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]; c, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    r = math.sqrt(c[2] + c[0] ** 2 + c[1] ** 2)
    return c[0], c[1], r, float(np.abs(np.hypot(x - c[0], y - c[1]) - r).max())


def split_run(q, tol=0.5):
    """⚠ 半径の違う円弧が続けて1本の C の列になっていることがある(松島: 外周 30NM と霞目 CTZ の半円)。
    先頭から1つの円に乗る間だけ伸ばして切り分ける"""
    out, i = [], 0
    while i < len(q) - 2:
        j = i + 2
        while j + 1 < len(q) and fitc(q[i:j + 2])[3] < tol: j += 1
        if fitc(q[i:j + 1])[3] < tol: out.append(q[i:j + 1])
        i = j
    return out


def find_page(ic, issue):
    sys.path.insert(0, HERE)
    from aip_pick import pick
    f = [x for x in pick(glob.glob(os.path.join(AIP, issue, 'AD2_Combine', '*.pdf'))) if os.path.basename(x).startswith(ic)][0]
    n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', f], capture_output=True, text=True).stdout).group(1))
    for p in range(1, n + 1):
        t = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-layout', f, '-'], capture_output=True, text=True).stdout
        if re.search(r'(?i)terminal control area', t) and not re.search(r'LATERAL LIMITS', t): return f, p
    raise SystemExit(f'{ic}: TCA の図のページが見つからない')


def words(f, p):
    h = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-bbox', f, '-'], capture_output=True, text=True).stdout
    return [(float(a), float(b), float(c), float(d), html_un(w)) for a, b, c, d, w in
            re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', h)]


def html_un(s):
    return s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')


def alt(s):
    s = s.strip().upper()
    if re.fullmatch(r'FL\d{2,3}', s): return int(s[2:]) * 100
    if re.fullmatch(r'[1-9]\d{2,4}', s) and int(s) >= 500: return int(s)     # 「023°T」の 023 などを除く
    return None


def build(ic, issue, verbose=True):
    C = CFG[ic]
    f, p = find_page(ic, issue)
    svg = subprocess.run(['pdftocairo', '-svg', '-f', str(p), '-l', str(p), f, '-'], capture_output=True, text=True).stdout
    P = svg_paths(svg)
    # 外周(ref_r_nm)の円弧で中心(=基準 navaid)と縮尺を決める。⚠ 外周は短い円弧に分かれていたり(仙台)、直線と1本のパスに
    #   つながっていたり(三沢)する。円弧の区間ごとに当てはめ、0.3rad 以上回る円弧のうち半径が一番大きいもの(=外周)を採る
    #   (短い円弧ほど中心が不安定・記号の小さな円は除く)
    best = None
    for x in P:
        if x['dash']: continue
        for q in [r for rr in x['runs'] for r in split_run(rr)] + ([x['pts']] if x['curve'] and not x['runs'] else []):
            if len(q) < 5: continue
            cx, cy, r, e = fitc(q)
            if e > 1.0 or r < 60: continue
            span = sum(math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1]) for i in range(len(q) - 1)) / r
            if span < 0.3: continue          # 仙台の外周の欠片は 0.36rad、中心が不安定な欠片は 0.26rad 以下
            if best is None or r > best[2] + 2 or (abs(r - best[2]) <= 2 and span > best[4]): best = (cx, cy, r, e, span)
    cx, cy, r, e, _ = best
    sc = r / C['ref_r_nm']
    if verbose: print(f'  {ic}: 図 p{p} 外周の円弧 中心 ({cx:.1f},{cy:.1f}) 半径 {r:.1f}pt → {sc:.3f} pt/NM(当てはめ誤差 {e:.2f}pt)')
    rot = math.radians(C['rot'])

    def nm(x, y):      # 図(pt)→ 基準 navaid を原点とする NM の平面(x 東・y 北)
        X, Y = (x - cx) / sc, -(y - cy) / sc
        return (X * math.cos(rot) + Y * math.sin(rot), -X * math.sin(rot) + Y * math.cos(rot))
    if C.get('anchors'):
        # 地図として縮尺どおりに描かれた図(鹿児島)は、CTR の円の中心(= ARP)で相似変換を当てる。
        #   anchors = [(図のおおよその位置 pt, (緯度, 経度)), …]。近く(4pt 以内)の円(半径 10〜30pt)の中心に寄せてから当てはめる
        cc = [fitc(q)[:3] for x in P for q in [r for rr in x['runs'] for r in split_run(rr)] if len(q) >= 4]
        cc = [(a, b) for a, b, r in cc if 10 <= r <= 30]
        Z, W_ = [], []
        for (px, py), (la, lo) in C['anchors']:
            a, b = min(cc, key=lambda t: math.hypot(t[0] - px, t[1] - py))
            if math.hypot(a - px, b - py) > 4: raise SystemExit(f'{ic}: 位置合わせの円が ({px},{py}) の近くに無い')
            bb, dd = _bd(C['center'][0], C['center'][1], la, lo)
            Z.append(complex(a, -b)); W_.append(complex(dd * math.sin(math.radians(bb)), dd * math.cos(math.radians(bb))))
        M = np.c_[np.array(Z), np.ones(len(Z))]
        (ka, kb), *_ = np.linalg.lstsq(M, np.array(W_), rcond=None)
        res = [abs(ka * z + kb - w) for z, w in zip(Z, W_)]
        sc = 1 / abs(ka)
        if verbose: print(f'     位置合わせ: {abs(ka) ** -1:.3f} pt/NM・図の上 {math.degrees(-np.angle(ka)):+.2f}°・残差 {[round(r, 2) for r in res]} NM')
        def nm(x, y):
            w = ka * complex(x, -y) + kb; return (w.real, w.imag)
    # 円弧の半径の一覧(検算用)
    if verbose:
        rs = sorted({round(math.hypot(*nm(*fitc(x['pts'])[:2])), 1) for x in P if x['curve'] and len(x['pts']) >= 8 and fitc(x['pts'])[3] < 0.5 and not x['dash']})
        rads = sorted({round(fitc(x['pts'])[2] / sc, 1) for x in P if x['curve'] and len(x['pts']) >= 8 and fitc(x['pts'])[3] < 0.5 and not x['dash']
                       and math.hypot(*nm(*fitc(x['pts'])[:2])) < 0.5})
        print(f'     基準 navaid を中心とする円弧の半径(NM): {rads}')
    W = words(f, p)
    # 高度の分数「上限 / 下限」(上下に並ぶ2語)
    # ⚠ 縮尺の小さい図(鹿児島)では隣の分数の下段と次の分数の上段も 12pt 以内に並ぶ(「4200」と「3000」で 4200/3000 ができた)。
    #   上段・下段とも互いに一番近い相手どうしだけを組にする
    cand = []
    for i, (x0, y0, x1, y1, w) in enumerate(W):
        u = alt(w)
        if u is None: continue
        for j, (a0, b0, a1, b1, w2) in enumerate(W):
            l = alt(w2)
            if l is None or l >= u: continue
            if -0.5 < b0 - y1 < 12 and abs((a0 + a1) / 2 - (x0 + x1) / 2) < 8:
                cand.append((abs(b0 - y1) + abs((a0 + a1) / 2 - (x0 + x1) / 2), i, j))
    bi, bj = {}, {}
    for c in cand:
        if c[1] not in bi or c < bi[c[1]]: bi[c[1]] = c
        if c[2] not in bj or c < bj[c[2]]: bj[c[2]] = c
    fr = []
    for c in cand:
        if bi[c[1]] is c and bj[c[2]] is c:
            (x0, y0, x1, y1, w), (a0, b0, a1, b1, w2) = W[c[1]], W[c[2]]
            fr.append({'b': (alt(w), alt(w2)), 'x': (x0 + x1) / 2, 'y': (y1 + b0) / 2, 'box': (min(x0, a0), y0, max(x1, a1), b1)})
    # ⚠ 文字の輪郭が図形で重ねて描かれている図がある(鹿児島: 「10000」「KAGOSHIMA」が文字と輪郭線の二重)。
    #   また分数の横棒は細い区画(鹿児島 PCA の箱)を横切って面を割る。どちらも区画の線から外す
    def inbox(x, bx, m):
        return all(bx[0] - m <= q[0] <= bx[2] + m and bx[1] - m <= q[1] <= bx[3] + m for q in x['pts'])
    def deco(x):
        if x['w'] >= 0.9 and any(inbox(x, w_[:4], 1.0) for w_ in W): return True      # 輪郭は 0.98/1.96pt(区画の短い弧 0.49pt は「10NM」の枠に収まる)
        return (not x['curve'] and len(x['pts']) == 2 and abs(x['pts'][0][1] - x['pts'][1][1]) < 0.3
                and any(inbox(x, q['box'], 1.5) for q in fr))
    lines = [LineString([nm(*q) for q in x['pts']]) for x in P if not x['dash'] and 0.3 <= x['w'] <= 2.5 and len(x['pts']) >= 2
             and not deco(x)]
    # ⚠ 線の端どうしが図の上でわずかに(0.1pt 程度)離れていて polygonize では面が閉じない。線に太さ EPS を持たせてつなぎ、
    #   囲まれた穴を区画にして EPS だけ太らせて戻す
    EPS = C.get('eps', 0.06)
    net = unary_union([l.buffer(EPS, cap_style=1) for l in lines])
    polys = net.geoms if hasattr(net, 'geoms') else [net]
    faces = [Polygon(h).buffer(EPS, join_style=2) for pg in polys for h in pg.interiors]
    faces = [g for g in faces if g.area > 0.02]
    # 図の外枠は TCA の線と別の塊で、その穴が図全体を覆う。ほかの面を中に含む面は外す
    reps = [g.representative_point() for g in faces]
    # ⚠ CTZ の円は中に navaid の記号(小さな面)を含むので、1つ含むだけでは外さない
    #   (記号は小さな面がいくつも重なる)。数えるのは 5NM² 以上の面だけ
    faces = [g for i, g in enumerate(faces) if sum(1 for j in range(len(faces)) if j != i and faces[j].area >= 5 and g.contains(reps[j])) < 2]
    # ⚠ 外周の太線は1本につながっていない(途中が細線の区間もある)ので外周の多角形では絞らない。
    #   高度の文字がある面を区画にし、文字の無い面は一覧に出して目で確かめる(図の外の枠・凡例の箱など)
    cells = faces
    # 記号: 英大文字1字(三沢 A/B/C)/ 丸数字(① / 文字化けした U+4DF5〜 = 松島・U+0518〜 = 小松)/ 小さな円の中の数字(千歳は円の図形+数字)
    circ = []
    for x in P:
        if x['curve'] and len(x['pts']) >= 8:
            a_, b_, r_, e_ = fitc(x['pts'])
            if 2.5 <= r_ <= 7 and e_ < 0.8: circ.append((a_, b_, r_))
    marks = []
    for x0, y0, x1, y1, w in W:
        w2 = w.replace('\u48a2', '').strip()
        mx, my, m = (x0 + x1) / 2, (y0 + y1) / 2, None
        if re.fullmatch(r'[A-Z]', w2):
            # ⚠ 回転した文字(「MISAWA PCA」など)の切れ端と区別するため、周り 18pt に他の文字が無い1字だけ(「MISAW」「A」は 15.8pt 離れて別の語になっていた)
            #   (コロン・数字は数えない: 凡例は「A : 10000/2500」)
            if not any((o[0], o[1]) != (x0, y0) and o[4].strip() not in (':', '：') and not re.fullmatch(r'[\d,]+', o[4].strip())
                       and math.hypot((o[0] + o[2]) / 2 - mx, (o[1] + o[3]) / 2 - my) < 18 for o in W): m = w2
        elif len(w2) == 1 and 0x2460 <= ord(w2) <= 0x2473: m = str(ord(w2) - 0x245F)
        elif len(w2) == 1 and 0x4DF5 <= ord(w2) <= 0x4E08: m = str(ord(w2) - 0x4DF4)
        elif len(w2) == 1 and 0x0518 <= ord(w2) <= 0x052B: m = str(ord(w2) - 0x0517)        # 小松: ①=U+0518
        elif re.fullmatch(r'\d{1,2}', w2) and any(math.hypot(mx - c0, my - c1) < c2 + 1 for c0, c1, c2 in circ): m = w2
        if m: marks.append({'m': m, 'x': mx, 'y': my, 'abc': m.isalpha(), 'x1': x1})
    # ⚠ 英字は回転した文字の切れ端(「SDE」の E など)と区別がつかない。凡例は「A :」とコロンが続くものだけ
    colon = [((x0 + x1) / 2, (y0 + y1) / 2) for x0, y0, x1, y1, w in W if w.strip() in (':', '：')]
    # 凡例: 記号の右の同じ行にある分数(「① 2999/2001 & 20000/8001」は2段)。次の記号の手前まで
    legend, used = {}, set()
    for mk in marks:
        if mk['abc'] and not any(0 < cx_ - mk['x1'] < 12 and abs(cy_ - mk['y']) < 5 for cx_, cy_ in colon): continue
        nxt = min([o['x'] for o in marks if o is not mk and abs(o['y'] - mk['y']) < 6 and o['x'] > mk['x']] or [1e9])
        row = sorted([i for i, q in enumerate(fr) if 0 < q['x'] - mk['x'] < 160 and q['x'] < nxt and abs(q['y'] - mk['y']) < 7], key=lambda i: fr[i]['x'])
        if row and fr[row[0]]['x'] - mk['x'] > 45: row = []          # 記号のすぐ右(45pt 以内)から始まる行だけ
        if row:
            legend[mk['m']] = [fr[i]['b'] for i in row]; used.update(row); mk['leg'] = True
    if verbose and legend: print('     凡例:', {k: v for k, v in legend.items()})
    # 区画に付ける印: 凡例に使っていない分数 + 凡例のある記号(凡例の行そのものは除く)。座標は図(pt)のまま
    labs = [(q['b'], (q['x'], q['y']), q['box']) for i, q in enumerate(fr) if i not in used]
    for mk in marks:
        if mk['m'] in legend and not mk.get('leg'):          # 凡例の行の記号そのものは除く
            for bnd in legend[mk['m']]: labs.append((bnd, (mk['x'], mk['y']), (mk['x'] - 4, mk['y'] - 5, mk['x'] + 4, mk['y'] + 5)))
    # 矢印(引き出し線): 文字の近く(20pt 以内)に端がある短い直線。文字が別の区画の中に書かれて矢印で隣を指していることがある
    #   (仙台の北端 4500・三沢の 2000/1999)。矢印があれば**矢印の先**の区画に付け、文字のある区画には付けない。2本なら2区画
    leaders = [(x['pts'][0], x['pts'][-1], x['w']) for x in P if not x['dash'] and x['w'] < C.get('lead_w', 1) and not x['curve'] and len(x['pts']) <= 3
               and abs(x['pts'][0][1] - x['pts'][-1][1]) > 0.5]          # 水平の短い線は上限/下限の間の横線
    # ⚠ 地図の入った図(鹿児島)では海岸線の切れ端も短い直線になる。海岸線は端が同じ太さの別の線の端とつながっているので外す
    ends = {}
    for x in P:
        for e in (x['pts'][0], x['pts'][-1]): ends.setdefault((round(x['w'], 2), round(e[0]), round(e[1])), []).append(e)
    def joined(e, w):
        return sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in ends.get((round(w, 2), round(e[0]) + dx, round(e[1]) + dy), [])
                   if math.hypot(q[0] - e[0], q[1] - e[1]) < 0.3) > 1
    leaders = [(a, b) for a, b, w in leaders if not (joined(a, w) or joined(b, w))]
    pts = []
    def dbox(q, bx):        # 点から文字の枠までの距離(pt)
        return math.hypot(max(bx[0] - q[0], 0, q[0] - bx[2]), max(bx[1] - q[1], 0, q[1] - bx[3]))
    for bnd, (lx, ly), bx in labs:
        tips = []
        for a2, b2 in leaders:
            for e0, e1 in ((a2, b2), (b2, a2)):
                # ⚠ 文字の「中心から」で見ると、近くを通る別の矢印(注記の箱から出る線)を拾った(仙台 4000)。文字の枠から 6pt 以内
                # ⚠ もう一方の端がほかの文字に付いている線はその文字の引き出し線(「KAGOSHIMA PCA」の線の先が 10000/5001 の横に来る)
                if dbox(e0, bx) < 6 and dbox(e1, bx) > C.get('lead_min', 12) and math.hypot(e1[0] - e0[0], e1[1] - e0[1]) < 60 \
                        and not any(dbox(e1, w_[:4]) < 3 and re.search(r'[A-Za-z]{2}', w_[4]) and not (bx[0] - 1 <= w_[0] and w_[2] <= bx[2] + 1 and bx[1] - 1 <= w_[1] and w_[3] <= bx[3] + 1) for w_ in W):
                    tips.append(e1)
        if tips and verbose: print(f'     矢印: {bnd[0]}/{bnd[1]} → {len(tips)} 本')
        for t in (tips or [(lx, ly)]): pts.append((bnd, nm(*t), bool(tips)))
    def cell_of(pt, arrow):
        P0 = Point(pt)
        for i, g in enumerate(cells):
            if g.contains(P0): return i
        # 矢印の先は境界線の上に載っていることが多い → 0.6NM 以内で一番近い区画
        d = sorted((g.distance(P0), i) for i, g in enumerate(cells))
        return d[0][1] if d and d[0][0] < (0.6 if arrow else 0.05) else None
    labs = [(bnd, ci) for bnd, pt, ar in pts for ci in [cell_of(pt, ar)] if ci is not None]
    out, miss = [], []
    if C.get('spec'):
        # 形は図の定義から(spec_*)、高度は凡例から。図の区画(記号のある面)と面積を並べて取り違えを見る
        S = globals()[C['spec']](C)
        # 検算: 区画どうしが重なっていないこと(定義の書き違いはここに出る)
        ks = list(S)
        for a in range(len(ks)):
            for b in range(a + 1, len(ks)):
                ov = S[ks[a]].intersection(S[ks[b]]).area
                if ov > 0.05: print(f'     ⚠ {ic}: 区画 {ks[a]} と {ks[b]} が {ov:.2f} NM² 重なっている')
        if verbose: print(f'     区画の合計 {sum(g.area for g in S.values()):.1f} NM² / 和 {unary_union(list(S.values())).area:.1f} NM²')
        geo = lambda cs: [dest(C['center'][0], C['center'][1], (math.degrees(math.atan2(X, Y)) + 360) % 360, math.hypot(X, Y)) for X, Y in cs]
        for n, g in S.items():
            bands = [n] if isinstance(n, tuple) else legend[str(n)]
            ch = sorted({round(cells[ci].area, 1) for mk in marks if mk['m'] == str(n) and not mk.get('leg')
                         for ci in [cell_of(nm(mk['x'], mk['y']), False)] if ci is not None} |
                        {round(cells[ci].area, 1) for bnd, ci in labs if bnd in bands})
            if verbose: print(f"       {str(n):>14} {bands}  定義 {g.area:6.1f} NM² / 図の面 {ch} NM²")
            parts = [q for q in (g.geoms if hasattr(g, 'geoms') else [g]) if q.area > 0.05]
            for q in parts:
                q = q.simplify(0.005)
                ring = geo(q.exterior.coords) if not q.interiors else [geo(q.exterior.coords)] + [geo(h.coords) for h in q.interiors]
                for u, l in bands:
                    out.append({'n': f"{C['name']} {u}/{l}", 'jp': C['jp'], 'k': 'TCA', 'icao': ic, 'up': u, 'lo': l, 'src': 'def',
                                'rmk': f"AD 2.17 添付図に書かれた定義({C['center_id']} からの弧・放射線、平行線、CTR)から作図", 'pts': ring,
                                '_a': round(q.area, 1)})
        return out, [], (cx, cy, sc, nm)
    for ci, g0 in enumerate(cells):
        bands = sorted({bnd for bnd, c in labs if c == ci}, key=lambda b: b[1])
        if not bands:
            if g0.area > 1: miss.append(g0)
            continue
        g = g0
        if g.geom_type == 'MultiPolygon': g = max(g.geoms, key=lambda q: q.area)
        g = g.simplify(0.01)
        geo = lambda cs: [dest(C['center'][0], C['center'][1], (math.degrees(math.atan2(X, Y)) + 360) % 360, math.hypot(X, Y)) for X, Y in cs]
        # 穴(区画の中の別の区画=CTZ など)があれば [外周, 穴…] のリングの配列で持つ(inArea・L.polygon がそのまま扱える)
        ring = geo(g.exterior.coords) if not g.interiors else [geo(g.exterior.coords)] + [geo(h.coords) for h in g.interiors]
        for u, l in bands:          # 1つの区画に高度帯が2つ以上(千歳の「2999/2001 & 20000/8001」)なら帯ごとに
            out.append({'n': f"{C['name']} {u}/{l}", 'jp': C['jp'], 'k': 'TCA', 'icao': ic, 'up': u, 'lo': l, 'src': 'svg',
                        'rmk': f"AD 2.17 添付図の線(ベクタ)から起こした近似の形({C['center_id']} 基準・"
                               f"{'CTR の円で位置合わせ' if C.get('anchors') else '図の縮尺で変換'}・誤差 0.1〜0.5NM 程度)", 'pts': ring,
                        '_a': round(g.area, 1)})
    if verbose:
        print(f'     区画 {len(out)}(高度の文字が無い面 {len(miss)}・面積 {[round(g.area, 1) for g in miss]} NM²)')
        for o in sorted(out, key=lambda o: (o['lo'], o['up'])): print(f"       {o['up']:>6}/{o['lo']:<6} {o['_a']:7.1f} NM²")
    return out, miss, (cx, cy, sc, nm)


def _bd(la1, lo1, la2, lo2):
    """真方位(°)と距離(NM)"""
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    d = 2 * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)) * R_NM
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360, d


class Kit:
    """図の定義から区画を組む道具。平面は基準 navaid 中心の方位・距離(dest の逆)、x 東・y 北(NM)。
    放射線は磁方位(var = 偏差・西 +)"""
    def __init__(self, C, var):
        from shapely.geometry import Point
        self.lat0, self.lng0 = C['center']; self.var = var; self.Point = Point
        h = open(os.path.join(ROOT, 'index.html')).read(); i = h.index('const ASP_POLY='); j = h.index(';\n', i)
        self.AP = {}
        for a in json.loads(h[i + 15:j]):
            if a.get('t') == 'ctr': self.AP.setdefault(a['icao'], a)

    def xy(self, la, lo):
        b, d = _bd(self.lat0, self.lng0, la, lo); return (d * math.sin(math.radians(b)), d * math.cos(math.radians(b)))

    @staticmethod
    def u(b): return (math.sin(math.radians(b)), math.cos(math.radians(b)))

    def half(self, P, b, right):
        """点 P を通る真方位 b の直線の右(進行方向に向かって)か左の半平面"""
        ux, uy = self.u(b); nx, ny = (uy, -ux) if right else (-uy, ux); B = 200
        return Polygon([(P[0] - ux * B, P[1] - uy * B), (P[0] + ux * B, P[1] + uy * B),
                        (P[0] + ux * B + nx * B, P[1] + uy * B + ny * B), (P[0] - ux * B + nx * B, P[1] - uy * B + ny * B)])

    def off(self, P, b, d):
        """P を真方位 b の直線の右へ d NM 平行移動した点"""
        ux, uy = self.u(b); return (P[0] + uy * d, P[1] - ux * d)

    def D(self, r): return self.Point(0, 0).buffer(r, 256)

    def wedge(self, m1, m2):
        """放射線 m1 から時計回りに m2 まで(磁方位)"""
        a1, a2 = m1 - self.var, (m2 if m2 > m1 else m2 + 360) - self.var
        n = max(2, int((a2 - a1) / 0.5))
        return Polygon([(0, 0)] + [(60 * self.u(a1 + (a2 - a1) * k / n)[0], 60 * self.u(a1 + (a2 - a1) * k / n)[1]) for k in range(n + 1)])

    def aca(self, ic, up):
        """進入管制区(aca.json の AIXM 由来)の区画の形"""
        for x in json.load(open(os.path.join(ROOT, 'aca.json')))['f']:
            if x.get('k') == 'ACA' and x.get('icao') == ic and x.get('up') == up:
                r = x['pts'] if isinstance(x['pts'][0][0], (int, float)) else x['pts'][0]
                return Polygon([self.xy(*q) for q in r]).buffer(0)
        raise SystemExit(f'{ic} ACA 上限 {up} が aca.json に無い')

    def ctr(self, ic):
        """管制圏(ASP_POLY・AIXM)の形"""
        a = self.AP[ic]
        if a.get('c'): return self.Point(*self.xy(*a['c'])).buffer(a['r'] / 1852, 256)
        return Polygon([self.xy(*q) for q in (a['pts'] if isinstance(a['pts'][0][0], (int, float)) else a['pts'][0])])


def spec_rjst(C):
    """松島 TCA(RJST AD2-10)を図の定義から組む
    ・弧: MXT から 30/25/20/18/13NM ・放射線: MXT の磁方位(図の偏差 VAR 8°W)
    ・SDE 007°T の線から東へ 4NM(凡例の 6000 と 10000 の境)・SDE 113°T の線から北東へ 5.5NM(南の境)
      … AIXM の松島進入管制区の辺と 0.01NM で一致
    ・YTE 030°T の線から 4NM(①の北西の辺)… AIXM の辺の頂点そのもの(YTE からの平行線とは子午線収差ぶん向きが違うので)
    ・⑨ = 松島 CTR(ARP 5NM)の真上、⑤ = 霞目 CTR(AIXM の形・南は東西の線で切れている)の真上で 007°T+4NM の線より西"""
    k = Kit(C, 8); D, wedge = k.D, k.wedge
    SDE = k.xy(38.13857, 140.92148)
    L4 = k.off(SDE, 7, 4)                                  # 右 = 東
    E4, W4 = k.half(L4, 7, True), k.half(L4, 7, False)
    N113 = k.half(k.off(SDE, 113, -5.5), 113, False)       # 左 = 北東
    Y0, Y1 = k.xy(38.56404, 140.5853), k.xy(39.0, 140.91002)  # AIXM の松島 ACA の辺(YTE 030°T から 4NM)
    SEY = k.half(Y0, math.degrees(math.atan2(Y1[0] - Y0[0], Y1[1] - Y0[1])), True)
    MC, KC = k.ctr('RJST'), k.ctr('RJSU')
    return {
        1: W4 & SEY & (D(30) - D(20)) & wedge(300, 100),
        2: (W4 & N113 & ((D(20) & wedge(290, 100)) | D(13))) - KC,
        3: W4 & N113 & (D(20) - D(13)) & wedge(260, 290),
        4: (W4 & N113 & (D(20) - D(13)) & wedge(180, 260)) - KC,
        5: KC & W4,
        6: E4 & (((D(30) - D(20)) & wedge(300, 10)) | ((D(25) - D(18)) & wedge(10, 80))),
        7: (E4 & N113 & D(20) & wedge(130, 10)) - MC,
        8: (E4 & N113 & ((D(18) & wedge(10, 80)) | (D(30) & wedge(80, 130)) | ((D(30) - D(20)) & wedge(130, 300)))) - MC,
        9: MC,
        10: (D(30) - D(25)) & wedge(10, 80),
    }


def spec_rjnk(C):
    """小松 TCA(RJNK AD2-10)を図の定義から組む
    ・弧: KMC から 30/25/20/17/15/9NM ・放射線: KMC の磁方位(偏差 8°W)
    ・062°・236° の破線から北西へ 4NM の2本の線 … AIXM の小松進入管制区(SFC〜7000 と その上)の境そのもの。
      頂点(CTZ の中・KMC の 340.8°/4.08NM)から北東・南西へ伸びる。北西側が上限 10000・南東側が上限 7000
    ・③の南西は 236° の破線から南東へ 4NM の線と 235° の放射線の間(図の線は 4.45NM・図の縮尺の誤差(北西の 4NM が 4.3)を見て 4NM とした)
    ・7000/6001 = 小松 CTR の真上 / 単独の「7000」は下限の記載なし
    ⚠ 図の放射線は 090° が 084° に描かれているなど、図の線を写すと最大 3NM ずれる"""
    k = Kit(C, 8); D, wedge = k.D, k.wedge
    A = k.xy(36.457, 136.36652)                                # AIXM の小松 ACA の頂点
    NE, SW = k.xy(36.74462, 136.85034), k.xy(36.11701, 135.89128)   # 頂点からの線と 30NM 弧の交点(AIXM)
    uNE = ((NE[0] - A[0]) / math.dist(NE, A), (NE[1] - A[1]) / math.dist(NE, A))
    uSW = ((SW[0] - A[0]) / math.dist(SW, A), (SW[1] - A[1]) / math.dist(SW, A))
    B = 100
    # 南東側(KMC を含む側)= 2本の線の南東。頂点から北東・南西へ伸ばし、南東へ大きく閉じる
    sx, sy = -(uNE[1] - uSW[1]), (uNE[0] - uSW[0])           # 2本の線の南東向きの法線(おおよそ)
    n = math.hypot(sx, sy); sx, sy = sx / n * B, sy / n * B
    if sx * (0 - A[0]) + sy * (0 - A[1]) < 0: sx, sy = -sx, -sy
    SEZ = Polygon([A, (A[0] + uNE[0] * B, A[1] + uNE[1] * B), (A[0] + uNE[0] * B + sx, A[1] + uNE[1] * B + sy),
                   (A[0] + uSW[0] * B + sx, A[1] + uSW[1] * B + sy), (A[0] + uSW[0] * B, A[1] + uSW[1] * B)])
    NWZ = D(30) - SEZ
    ax = k.u(236 - 8)
    L4SE = k.half(k.off((0, 0), 236 - 8, -4), 236 - 8, True)  # 236° の線から南東へ 4NM の線の北西側(236° に向かって右)
    CT = k.ctr('RJNK')
    c3 = ((wedge(64, 90) & D(9)) | (wedge(50, 64) & (D(17) - D(9))) | (L4SE & wedge(180, 235) & D(9))) - CT
    return {
        1: (SEZ & wedge(250, 30) & D(30)) - CT,
        2: (SEZ & ((wedge(30, 64) & D(9)) | (wedge(30, 50) & D(20)) | (wedge(235, 250) & D(20)))) - CT,
        3: c3,
        4: NWZ & wedge(180, 250) & (D(30) - D(20)),
        (7000, 4000): SEZ & wedge(50, 64) & (D(30) - D(17)),
        (7000, 5000): ((wedge(64, 90) & (D(30) - D(9))) | (wedge(90, 235) & D(9)) | (wedge(195, 215) & (D(25) - D(9)))) - CT - c3,
        (7000, 6000): (wedge(155, 195) & (D(15) - D(9))) | (wedge(180, 195) & (D(25) - D(15))),
        (7000, None): (wedge(90, 155) & (D(15) - D(9))) | (wedge(155, 180) & (D(25) - D(15))),
        (7000, 3500): SEZ & ((wedge(215, 235) & (D(30) - D(9))) | (wedge(235, 250) & (D(30) - D(20)))),
        (10000, 1500): (NWZ & wedge(250, 30)) - CT,
        (10000, 2000): (NWZ & (wedge(30, 90) | wedge(180, 250)) & D(20)) - CT,
        (10000, 3000): NWZ & wedge(30, 40) & (D(30) - D(20)),
        (10000, 4000): NWZ & wedge(40, 90) & (D(30) - D(20)),
        (7000, 6001): CT,
    }


def spec_rjnh(C):
    """浜松 TCA(RJNH AD2-8)を図の定義から組む。図は真北が上・放射線は LHT の磁方位(偏差 8°W)
    ・弧: LHT から 20/18/16/13/11/9/7NM(図では 9NM と 7NM が同じ半径に描かれている)
    ・北西の上限 4000 の区画・南の上限 10000 の区画の境(KCC 40NM・CBE 33NM・KCC 30NM の弧、350353N–345851N、
      343836N–343846N–094°47′T の線)は AIXM の浜松進入管制区の3区画(〜4000 / 〜6000 / 〜FL140)の形そのもの
    ・OUT OF TCA = 〜4000 の区画のうち 335° の放射線より東・13NM より外
    ・単独の「4000」「6000」は下限の記載なし"""
    k = Kit(C, 8); D, wedge = k.D, k.wedge
    A4, A6, A14 = k.aca('RJNH', 4000), k.aca('RJNH', 6000), k.aca('RJNH', 14000)
    CT = k.ctr('RJNH')
    OUT = A4 & (D(20) - D(13)) & wedge(335, 90)
    s10 = A14 & D(20) & wedge(250, 300)
    return {
        (4000, None): (A4 & wedge(300, 90)) - OUT,
        (4000, 2500): A4 & wedge(180, 300),
        (6000, 2500): (A6 & wedge(250, 300)) - D(7),
        (10000, 2500): s10,
        (10000, 1800): (A14 & D(20)) - s10,
        (6000, 1800): (A6 & ((wedge(115, 250) & D(20)) | (wedge(90, 115) & D(11)) | (wedge(250, 300) & D(7)))) - CT,
        (6000, 2000): ((wedge(90, 115) & (D(20) - D(11))) | (((wedge(65, 83) & D(9)) | (wedge(83, 90) & D(11))) - CT)),
        (6000, 3000): ((wedge(300, 65) & D(9)) - CT) | (wedge(65, 71) & (D(13) - D(9))) | (wedge(71, 83) & (D(16) - D(9)))
                      | (wedge(83, 90) & (D(20) - D(11))),
        (6000, 4000): (A6 & wedge(300, 65) & (D(13) - D(9))) | (wedge(65, 71) & (D(20) - D(13))) | (wedge(71, 83) & (D(20) - D(16))),
        (6000, 4500): (A6 & wedge(300, 65) & (D(20) - D(13))) - (wedge(10, 50) & (D(20) - D(18))),
        (6000, None): wedge(10, 50) & (D(20) - D(18)),
        (6000, 4001): CT,
    }


def main():
    issue = sys.argv[sys.argv.index('--airac') + 1] if '--airac' in sys.argv else sorted(os.listdir(AIP))[-1]
    ics = [a for a in sys.argv[1:] if re.fullmatch(r'[A-Z]{4}', a)] or list(CFG)
    res = {ic: build(ic, issue)[0] for ic in ics}
    if '--write' in sys.argv:
        A = json.load(open(os.path.join(ROOT, 'aca.json')))
        A['f'] = [x for x in A['f'] if not (x.get('k') == 'TCA' and x.get('icao') in res)]
        for ic, v in res.items():
            for o in v: o.pop('_a', None); A['f'].append(o)
        json.dump(A, open(os.path.join(ROOT, 'aca.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        print('aca.json を更新', sum(len(v) for v in res.values()), '区画')


if __name__ == '__main__':
    main()
