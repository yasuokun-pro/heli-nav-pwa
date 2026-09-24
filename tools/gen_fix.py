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
    **名前ごとに±3行から一番近い未使用の座標を探す**(局所探索)なら1点の異常は伝播しない
  - 名前は5文字のFIX(ABASA…)のほかに、**navaidの名前**(AOMORI, CHITOSE, HACHIJOJIMA…)が
    義務位置通報点として混ざる。略号欄がその navaid の ID(MRE, CHE…)、FIXは '-'
  - 長い navaid 名は**2行に折れる**(HACHIJOJI / MA)。前の行が8文字以上で次の行が3文字以下なら継ぐ
  - カナと▲△は**名前の行か、その次の行**(次の行に別の名前が無いとき)。±2行で拾うと隣の点のカナが混ざる
  - 方位/距離の欄は開始桁が揺れる。桁で切らず**略号('-' か 3文字ID)の右側**を取る
  - 見出しの POINT(REPORTING POINT) や AIP/Civil/ENR の行は名前ではないので除く
"""
import os, re, sys, json, glob, subprocess
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


def find_pdf():
    for pat in (AIP_ROOT + '/1_AIP (PDF)/*/ENR_*.pdf',
                AIP_ROOT + '/1_AIP (PDF)/*/ENR_*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: return f[-1]
    return None


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
            # ⚠ 見分け方は「1行目にN緯度、2行目にE経度」が割れて乗っていること
            if i+1 < len(L):
                m2 = name_at(L[i+1])
                if m2 and LAT_RE.search(L[i]) and LON_RE.search(L[i+1]) and not LON_RE.search(L[i]):
                    nm += ('' if len(m2.group(1)) <= 3 else ' ') + m2.group(1)
                    L[i+1] = L[i+1].replace(m2.group(1), ' '*len(m2.group(1)), 1)
            names.append((i, nm))
        i += 1
    lats = {}; lons = {}
    for i, l in enumerate(L):
        for mm in LAT_RE.finditer(l): lats.setdefault(i, []).append(mm.group(1))
        for mm in LON_RE.finditer(l): lons.setdefault(i, []).append(mm.group(1))
    nlat = sum(len(v) for v in lats.values()); nlon = sum(len(v) for v in lons.values())
    if not (len(names) == nlat == nlon):
        print(f'⚠ 数が合わない: 名前{len(names)} N{nlat} E{nlon}', file=sys.stderr)

    def take(store, i):                                # ±3行で一番近い未使用の座標
        for d in (0, 1, -1, 2, -2, 3, -3):
            j = i+d
            if store.get(j): return store[j].pop(0)
        return None
    out, miss = [], []
    for ni, nm in names:
        la = take(lats, ni); lo = take(lons, ni)
        if la is None or lo is None:
            miss.append(nm); continue
        nxt = L[ni+1] if ni+1 < len(L) else ''
        near = [L[ni]] + ([nxt] if not name_at(nxt) else [])   # 名前の行と、名前の無い次の行
        blob = '\n'.join(near)
        comp = 1 if '▲' in blob else (0 if '△' in blob else None)
        kana = ''.join(re.findall(r'[ァ-ヶー]', blob))
        win = L[max(0, ni-2):ni+3]
        routes = []
        for w in win:
            for r in ROUTE_RE.findall(w[34:72]):
                if r not in routes: routes.append(r)
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
    left = sum(len(v) for v in lats.values())
    print(f'  読み取り {len(out)} 点 / 座標の無い名前 {len(miss)} {miss[:8]} / 余った座標 {left}', file=sys.stderr)
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
