#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIX(重要地点) 生成 (fix.json)
=============================
出典: AIP Japan **ENR 4.3 NAME-CODE DESIGNATORS FOR SIGNIFICANT POINTS**

使い方:
  python3 tools/gen_fix.py            # fix.json を出力

⚠ 表の癖(2026-09 に確認)
  - 1点が 1〜3行に割れる。名前・カナ・N緯度・E経度・ルート列・略号・方位距離の
    **どれが同じ行に乗るかが点ごとに違う**(N緯度が名前の1行上に来ることもある)
  - 名前・N緯度・E経度をそれぞれ取り出して組にするが、**文書順のk番目どうしを組にしてはいけない**。
    座標の無い点が1つあるだけで、それ以降が全部1つずつずれる(実際に後半1,089点がずれた)。
    ⚠ かといって**名前ごとに近い座標を貪欲に取る**のも駄目(20261001 で段組が詰まり、1行下の点の緯度を
    先取りして150点が玉突きでずれた)。**順序を保つ最小コストの対応づけ(DP)**にしてある(`align()`)
  - 名前は5文字のFIX(ABASA…)のほかに、**navaidの名前**(AOMORI, CHITOSE, HACHIJOJIMA…)が
    義務位置通報点として混ざる。略号欄がその navaid の ID(MRE, CHE…)、FIXは '-'
  - 長い navaid 名は**2行に折れる**(HACHIJOJI / MA)。1行目にN緯度・続きの行にE経度が乗るのが目印。
    ⚠ 20261001 から続きの行が**2行下**に来ることがある(間に ▲ とルート列だけの行)
  - カナと▲△は**名前の行か、その次の行**(次の行に別の名前が無いとき)。±2行で拾うと隣の点のカナが混ざる
  - 方位/距離の欄は開始桁が揺れる。桁で切らず**略号('-' か 3文字ID)の右側**を取る
  - 見出しの POINT(REPORTING POINT) や AIP/Civil/ENR の行は名前ではないので除く
"""
import os, re, sys, json, glob, subprocess, collections
# AIP一式の置き場(SWIMから落としたもの)。⚠ .gitignore 済み・公開リポジトリには入れない
AIP_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'aip'))

HERE = os.path.dirname(os.path.abspath(__file__))
BLACK = {'POINT', 'RNAV', 'STAR', 'WAY', 'AIP', 'ENR', 'CIVIL', 'INTENTIONALLY', 'LEFT',
         'BLANK', 'NAME', 'COMPULSORY', 'NON', 'REPORTING', 'ATS', 'ABBREV', 'BRG', 'DIST',
         'FM', 'NAVAID', 'JAPAN', 'AVIATION', 'BUREAU', 'EFF'}
NAME_RE = re.compile(r'^[\s▲△]{0,12}([A-Z]{2,})(?:\s|$)')
LAT_RE = re.compile(r'(?<!\d)(\d{6}\.\d{2})N(?!\d)')
LON_RE = re.compile(r'(?<!\d)(1\d{6}\.\d{2})E(?!\d)')
ROUTE_RE = re.compile(r'\b((?:[A-Z]{1,2}\d{1,3})|OTR\d+)\b')
ABBR_RE = re.compile(r'(?:^|\s)(-|[A-Z]{3})(?=\s|$)')


def wrap_names():
    """2行に折れうる長い名前(空白抜き・大文字)。navaid 名(ENR 4.1)に、ENR 4.1 に無い飛行場の局名を足す"""
    w = {'HACHIJOJIMA', 'MINAMIDAITO', 'SHIMOJISHIMA', 'TOKUNOSHIMA', 'ISHIGAKIJIMA', 'MINAMITORISHIMA'}
    try:
        t = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'navaids.gen.js'), encoding='utf-8').read()
        w |= {n.upper().replace(' ', '') for n in re.findall(r'"n":"([^"]+)"', t)}
    except OSError:
        pass
    return w


WRAP = wrap_names()


def find_pdf():
    """最新の ENR。`--airac 20260903` で版を固定できる(発効前の版を読んで公開しないため)"""
    want = sys.argv[sys.argv.index('--airac')+1] if '--airac' in sys.argv else None
    f = sorted(glob.glob(AIP_ROOT + '/1_AIP (PDF)/*/ENR_*.pdf'))
    if want: f = [x for x in f if want in x]
    return f[-1] if f else None


def dms(v, is_lon):
    d = 3 if is_lon else 2
    return round(int(v[:d]) + int(v[d:d+2])/60 + float(v[d+2:])/3600, 6)


def section(txt):
    """ENR 4.3 の本体(目次ではなく本文)を切り出す"""
    L = txt.split('\n')
    s = e = None
    for i, l in enumerate(L):
        if s is None and re.search(r'ENR 4\.3\s', l) and i > 5000:
            s = i
        elif s is not None and re.search(r'ENR 4\.4\s+航空地上灯火|ENR 4\.4 AERONAUTICAL', l):
            e = i; break
    return L[s:e]


def name_at(l):
    m = NAME_RE.match(l)
    if m and m.group(1) not in BLACK and m.start(1) < 20: return m
    return None


def parse(L):
    L = list(L)
    names = []
    i = 0
    while i < len(L):
        m = name_at(L[i])
        if m:
            nm = m.group(1)
            # 2行に折れた navaid 名(HACHIJOJI/MA、MINAMI/DAITO)。
            # ⚠ 折れ方は版で変わる。20261001 では続き(MA / DAITO)が**2行下**に来て、座標の乗る行も違った。
            #   座標の位置で見分けるのはやめ、**つないだ名前が既知の navaid 名になるか**で決める(WRAP)
            for j in (i+1, i+2):
                if j >= len(L): break
                m2 = name_at(L[j])
                if not m2: continue
                if (nm + m2.group(1)) in WRAP:
                    nm += ('' if len(m2.group(1)) <= 3 else ' ') + m2.group(1)
                    L[j] = L[j].replace(m2.group(1), ' '*len(m2.group(1)), 1)
                break
            names.append((i, nm))
        i += 1
    lats = {}; lons = {}
    for i, l in enumerate(L):
        for mm in LAT_RE.finditer(l): lats.setdefault(i, []).append(mm.group(1))
        for mm in LON_RE.finditer(l): lons.setdefault(i, []).append(mm.group(1))
    nlat = sum(len(v) for v in lats.values()); nlon = sum(len(v) for v in lons.values())
    if not (len(names) == nlat == nlon):
        print(f'⚠ 数が合わない: 名前{len(names)} N{nlat} E{nlon}', file=sys.stderr)

    # ⚠ 名前ごとに「近い未使用の座標」を貪欲に取る方式は、20261001 の詰まった段組で破綻した
    #   (AMARB が1行下の AMARU の緯度を先に取り、以降が玉突きで150点ずれた)。
    #   座標も名前も**文書順に並んでいる**ことを使い、順序を保ったまま行の距離の合計が最小になる
    #   対応づけ(編集距離と同じDP)にする。座標の無い名前・名前の無い座標は「飛ばす」で吸収する
    def align(store):
        pos = [(i, v) for i in sorted(store) for v in store[i]]
        N, M, SKIP, BAND = len(names), len(pos), 8, 80
        INF = float('inf')
        cost = [[INF]*(M+1) for _ in range(N+1)]; back = [[0]*(M+1) for _ in range(N+1)]
        cost[0][0] = 0
        for i in range(N+1):
            lo_j = max(0, i-BAND); hi_j = min(M, i+BAND)
            for j in range(lo_j, hi_j+1):
                c = cost[i][j]
                if c == INF: continue
                if i < N and j < M:                                          # 組にする
                    d = abs(names[i][0] - pos[j][0])
                    if d <= 3 and c+d < cost[i+1][j+1]: cost[i+1][j+1] = c+d; back[i+1][j+1] = 1
                if i < N and c+SKIP < cost[i+1][j]: cost[i+1][j] = c+SKIP; back[i+1][j] = 2   # 名前だけ
                if j < M and c+SKIP < cost[i][j+1]: cost[i][j+1] = c+SKIP; back[i][j+1] = 3   # 座標だけ
        res = [None]*N; i, j = N, M; left = 0
        while i or j:
            b = back[i][j]
            if b == 1: res[i-1] = pos[j-1]; i -= 1; j -= 1       # (行, 値)
            elif b == 2: i -= 1
            else: left += 1; j -= 1
        return res, left
    alat, left_lat = align(lats); alon, _ = align(lons)

    # ── 各行がどの点のものかを決める ──
    # ⚠ 以前は「名前の行の前後2行」を窓にしていたが、20261001 は段組が詰まって**隣の点の経路・評定・カナが混ざった**
    #   (231点)。点ごとに 名前・緯度・経度の行(アンカー)を持ち、各行を**一番近いアンカーの点**に割り当てる。
    #   同じ距離なら、その行がアンカーの範囲(最小〜最大の行)の内側にある点を優先する
    anc = []
    for k, (ni, nm) in enumerate(names):
        a = [ni] + [x[0] for x in (alat[k], alon[k]) if x]
        anc.append((min(a), max(a), a))
    owner = {}
    for k, (lo_, hi_, a) in enumerate(anc):
        for l in range(lo_ - 3, hi_ + 4):
            d = min(abs(l - x) for x in a)
            if d > 3: continue
            inside = lo_ <= l <= hi_
            key = (d, 0 if inside else 1)
            if l not in owner or key < owner[l][0]: owner[l] = (key, k)
    own = {}
    for l, (_, k) in owner.items(): own.setdefault(k, []).append(l)

    # ── 経路欄は折り返して上下の行にまたがる(KOCHI は3行目が点の行より上)。行末がカンマなら次の経路行へ続く。
    #   続いている行を1本の鎖にし、鎖ごとに**行の持ち主の多数決**で点に割り当てる(同数なら鎖の最後の行の持ち主) ──
    rline = {l: ROUTE_RE.findall(w[34:72]) for l, w in enumerate(L) if ROUTE_RE.findall(w[34:72])}
    chains, seen = [], set()
    for l in sorted(rline):
        if l in seen: continue
        ch = [l]; seen.add(l)
        while L[ch[-1]][34:72].rstrip().endswith(','):
            nx = next((j for j in (ch[-1]+1, ch[-1]+2) if j in rline and j not in seen), None)
            if nx is None: break
            ch.append(nx); seen.add(nx)
        chains.append(ch)
    rt_of = {}
    for ch in chains:
        ks = [owner[l][1] for l in ch if l in owner]
        if not ks: continue
        c = collections.Counter(ks).most_common()
        k = c[0][0] if len(c) == 1 or c[0][1] > c[1][1] else ks[-1]
        for l in ch:
            for r in rline[l]:
                if r not in rt_of.setdefault(k, []): rt_of[k].append(r)

    out, miss = [], []
    for k, (ni, nm) in enumerate(names):
        if alat[k] is None or alon[k] is None:
            miss.append(nm); continue
        la = alat[k][1]; lo = alon[k][1]
        win = [L[l] for l in sorted(own.get(k, [ni])) if 0 <= l < len(L)]
        blob = '\n'.join(w[:34] for w in win)                 # ▲△とカナは名前の欄(左34桁)だけ見る
        comp = 1 if '▲' in blob else (0 if '△' in blob else None)
        kana = ''.join(re.findall(r'[ァ-ヶー]', blob))
        routes = rt_of.get(k, [])
        abbr, brg = None, []
        for w in win:
            m = ABBR_RE.search(w[58:82])
            if m:
                cand = m.group(1)
                if cand == '-' or (cand not in BLACK and abbr is None):
                    if abbr is None: abbr = cand
                    rest = w[58+m.end():].strip()
                    if rest and ('°' in rest or 'NM' in rest): brg.append(rest)
                    continue
            # ⚠ 方位/距離の開始桁は揺れる(KOSKA は桁71から)。桁で切らず "ddd°/" の最初の位置から取る
            mb = re.search(r'\d{3}°/\d', w[50:])
            tail = w[50+mb.start():].strip() if mb else ''
            # ⚠ 方位/距離は座標と同じ行に乗ることがある(KOSKA: "351520.97N   021°/33.7NM XAC, 332°/21.1NM TET…")。
            #   行全体に座標があるからと捨てると、そういう点の評定がまるごと落ちる。桁74以降だけを見る
            if tail and ('°' in tail or 'NM' in tail) and not LAT_RE.search(tail) and not LON_RE.search(tail):
                brg.append(tail)
        rec = dict(n=nm, lat=dms(la, False), lng=dms(lo, True))
        if comp is not None: rec['c'] = comp
        if abbr and abbr != '-': rec['id'] = abbr
        if routes: rec['rt'] = routes
        if brg: rec['brg'] = re.sub(r'\s+', ' ', ' '.join(brg)).strip(' ,')
        if kana: rec['ja'] = kana
        out.append(rec)
    print(f'  読み取り {len(out)} 点 / 座標の無い名前 {len(miss)} {miss[:8]} / 余った座標 {left_lat}', file=sys.stderr)
    bad = [x['n'] for x in out if not (20 < x['lat'] < 50 and 120 < x['lng'] < 165)]   # 福岡FIRの東端は160E超
    if bad: print(f'  ⚠ 日本の外の座標: {bad}', file=sys.stderr)
    return out


def main():
    pdf = find_pdf()
    if not pdf:
        print('ENRのPDFが無い', file=sys.stderr); sys.exit(1)
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
    f = parse(section(txt))
    eff = os.path.basename(os.path.dirname(pdf))
    dst = os.path.join(HERE, '..', 'fix.json')
    json.dump({'eff': eff, 'src': 'AIP Japan ENR 4.3', 'f': f},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    comp = sum(1 for x in f if x.get('c') == 1)
    nav = sum(1 for x in f if 'id' in x)
    print(f'{len(f)} 点 (義務通報点 {comp} / navaid名 {nav}) → fix.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')


if __name__ == '__main__':
    main()
