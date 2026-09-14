#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空路 生成 (awy.json)
======================
出典: AIP Japan **ENR 3.1 LOWER ATS ROUTES**(A/B/G/R/V/W) と **ENR 3.3 RNAV ROUTES**(Y/Z)
      と **ENR 3.5.1 Direct routes**(直行経路。navaid/FIX 間の公示された直行区間。k='DCT')

使い方:
  python3 tools/gen_awy.py            # awy.json を出力

⚠ 表の癖(2026-09 に確認)
  - どちらも「点(名前+座標)」と「点と点の間の区間属性」が縦に並ぶ。**区間属性の置き場が
    3.1 と 3.3 で違う**:
      3.1: 2点の間の行に散る。"----" の上下が磁方位(往/復)、その右が距離、さらに右が MEA
      3.3: **点の座標の行そのもの**に、次の点までの 磁方位・距離・上限・MEA・方向矢印 が乗る。
           次の行の [真方位] [MOCA] は角括弧
  - 点の名前: "▲ KUSHIMOTO VORTAC(KEC)" / "▲ KAGOSHIMA" + 次行 "VORTAC(HKC)" / "△ ALBAT" /
    3.3 では記号無しの " YOROI" もある。**座標行を点の単位**にして、名前は直前の非空行から取る
  - ページをまたぐと見出しが挟まり、"A1 (Cont'd)" で続く。designator が同じなら同じ経路に継ぐ
  - 3.3 の designator の直後に "(RNAV5)" と "[VOR/DME, DME/DME, INS or IRS, GNSS]" (使えるセンサ)
  - 方向矢印 ↓↑: 左が Odd(奇数千ft/FL)、右が Even の列。位置(桁)でどちらか決める
  - **3.5.1 直行経路**は書式がまるで違う(座標が無い)。"1.n WAKKANAI VOR/DME (WKE VOR/DME)" の
    見出しの下に 1行=1経路で "WKE VOR/DME  144°  324° MVE VOR/DME"、その上の行に距離(95nm)、
    下の行に MEA(5000)。途中点があると "WKE VOR/DME 175° PANKE 355° AWE VOR/DME" のように増え、
    距離と MEA は**桁位置**で区間に対応する。
    ⚠ 座標は navaid(navaids.gen.js)と FIX(fix.json)から引く。"TBE 10DME" のような DME フィックスは
      経路の直線上で TBE から 10nm の点を作る(経路は直線なので両端から求まる)
    ⚠ 同じ経路が両端の見出しに1回ずつ載る(WKE→MVE と MVE→WKE)。端点の組で1本にまとめ、逆向きの
      磁方位は rmag に入れる
    ⚠ "← 6000 5000 →" は方向別 MEA。大きい方を mea にして rmk に両方残す
"""
import os, re, sys, json, glob, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
COORD = re.compile(r'(\d{6}(?:\.\d+)?)N\s*/?\s*(1\d{6}(?:\.\d+)?)E')
DESIG = re.compile(r'^\s{0,6}([A-Z]{1,3}\d{1,3})\s*(\(Cont\'d\))?\s*(?:\S.*)?$')
NAVID = re.compile(r'(VORTAC|VOR/DME|VOR|TACAN|DME|NDB)\s*\(([A-Z]{2,3})\)')


def find_pdf():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/ENR_*.pdf',
                '~/Downloads/1_AIP (PDF)/*/ENR_*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: return f[-1]
    return None


def dms(v, is_lon):
    d = 3 if is_lon else 2
    return round(int(v[:d]) + int(v[d:d+2])/60 + float(v[d+2:])/3600, 6)


def cut(txt, start_pat, end_pat):
    L = txt.split('\n'); s = e = None
    for i, l in enumerate(L):
        if s is None and re.search(start_pat, l) and i > 5000: s = i
        elif s is not None and re.search(end_pat, l): e = i; break
    return L[s:e]


def is_header(l):
    return bool(re.search(r'Civil Aviation Bureau|^\s*AIP Japan|ENR 3\.\d-\d|Route designator|'
                          r'Name of significant|Coordinates\s|^\s*\d\s+\d\s+\d|INTENTIONALLY|'
                          r'Track\s+|cruising levels|\(RNP type\)|Way-point|IDENT of|Odd\s+Even|'
                          r'\[Available SENSOR\]|Controlling unit|classification|\[MOCA\]|\(FT or FL\)|'
                          r'TRACK\]|Geodetic|Navigation specification|Upper limits|Lower limits|'
                          r'Airspace|Frequency|Critical DME|DMEGAP|Remarks|Lateral|limits|'
                          r'-OVER|\(NM\)|\(COP\)|Direction of|VOR/DME\s*$|^\s*RDL|^\s*MAG(?![A-Z])|^\s*\(GEO\)', l))


def point_name(L, ci):
    """座標行 ci の点の名前と navaid ID
    ⚠ 名前は座標行の**1〜5行上**にある。間に '----' や磁方位(163)・[真方位]の行、
      "VORTAC(HKC)" だけの行、空行が挟まるので「直前の非空行」では取れない(63点落ちた)。
      左の列(桁0〜27)だけを見て上へたどり、英字で始まる行を名前とする"""
    nid = None
    for j in range(ci-1, max(-1, ci-7), -1):
        a = L[j][:28].strip()
        if not a: continue
        m = NAVID.search(L[j])
        if m and not nid: nid = m.group(2)
        a = re.sub(r'\s*' + NAVID.pattern, '', a).strip()
        a = re.sub(r'^[▲△]\s*', '', a)
        a = a.replace('*', '').strip()                # '*ADKAK' / 'VOR/DME(MYE)*' の注記印
        a = re.sub(r'\s*\[.*$', '', a)               # 3.3 で名前の右に [真方位] が来る
        if not a or re.match(r'^[-\d\[\]. ]+$', a): continue   # '----' / 磁方位 / [真方位]
        if not re.match(r'^[A-Z]', a) or is_header(L[j]): return None, nid
        m2 = re.match(r'^([A-Z][A-Z ]*[A-Z]|[A-Z])(?:\((.*?)\))?', a)
        if not m2: return None, nid
        nm = m2.group(1).strip()
        if m2.group(2) and re.fullmatch(r'[A-Z]{2,3}', m2.group(2)): nid = nid or m2.group(2)
        return nm, nid
    return None, nid


def parse_31(L):
    """ENR 3.1: 区間属性は2点の間の行に散る"""
    routes = {}; cur = None; pts = []; between = []
    def flush_between(seg, lines):
        # 磁方位: '----' の行の上と下で、桁30〜46に3桁の数字が単独で乗っている最寄りの行
        # ⚠ 備考欄の "247°37'T" が同じ行にいることがあるので桁で絞る
        def trk(l):
            m = re.search(r'^\s{28,46}(\d{3})(?=\s|$)', l)
            return int(m.group(1)) if m else None
        for k, l in enumerate(lines):
            if '----' not in l: continue
            for j in range(k-1, max(-1, k-4), -1):
                if trk(lines[j]) is not None: seg['mag'] = trk(lines[j]); break
            for j in range(k+1, min(len(lines), k+4)):
                if trk(lines[j]) is not None: seg['rmag'] = trk(lines[j]); break
        for l in lines:
            for tok in re.finditer(r'\bFL(\d{2,3})\b|(?<![\d.])(\d{1,5}(?:\.\d)?)(?![\d.°\'])', l):
                col = tok.start()
                if tok.group(1):
                    if 50 <= col <= 68: seg.setdefault('mea', 'FL'+tok.group(1))
                else:
                    v = float(tok.group(2))
                    if v >= 1000 and 52 <= col <= 68 and 'mea' not in seg: seg['mea'] = int(v)
                    elif v < 400 and 40 <= col <= 52 and 'dist' not in seg: seg['dist'] = v
        return seg
    i = 0
    while i < len(L):
        l = L[i]
        md = DESIG.match(l)
        if md and not COORD.search(l):
            cur = md.group(1); routes.setdefault(cur, {'n': cur, 'pts': [], 'segs': []})
            if not md.group(2): pass
            i += 1; continue
        if cur is None or is_header(l): i += 1; continue
        mc = COORD.search(l)
        # ⚠ 備考欄(桁60〜)にも空域の頂点座標が書かれる(出雲 XZE の「355724N / 1305105E」)。点は左端の座標だけ
        if mc and mc.start() < 30:
            nm, nid = point_name(L, i)
            p = {'n': nm, 'lat': dms(mc.group(1), False), 'lng': dms(mc.group(2), True)}
            if nid: p['id'] = nid
            R = routes[cur]
            if R['pts'] and between:
                seg = flush_between({'a': R['pts'][-1]['n'], 'b': nm}, between)
                R['segs'].append(seg)
            if not R['pts'] or R['pts'][-1]['n'] != nm: R['pts'].append(p)
            between = []
        else:
            if l.strip() and not re.match(r'^\s*[▲△]', l): between.append(l)
            elif re.match(r'^\s*[▲△]', l): pass
        i += 1
    for R in routes.values():
        last = {}
        for s in R['segs']:
            for key in ('mea', 'mag', 'rmag'):
                if key in s: last[key] = s[key]
                elif key in last: s[key] = last[key]; s.setdefault('inh', []).append(key)
    return routes


def parse_33(L):
    """ENR 3.3: 区間属性は点の座標行に乗る"""
    routes = {}; cur = None
    col_odd = col_even = None
    for l in L:
        m = re.search(r'\bOdd\s+Even\b', l)
        if m: col_odd = m.start(); col_even = m.start()+len('Odd  '); break
    i = 0
    while i < len(L):
        l = L[i]
        md = DESIG.match(l)
        if md and not COORD.search(l) and re.match(r'^\s{0,6}[YZ]\d', l):
            cur = md.group(1); R = routes.setdefault(cur, {'n': cur, 'pts': [], 'segs': []})
            # 直後の数行に (RNAV5) と [センサ]
            for k in range(i+1, min(i+8, len(L))):
                ms = re.search(r'\((RNAV\s*\d+|RNP\s*\d+(?:\.\d+)?)\)', L[k])
                if ms and 'spec' not in R: R['spec'] = ms.group(1).replace(' ', '')
                # ⚠ センサ一覧は左列で2行に折れる "[VOR/DME, DME/DME," / "INS or IRS, GNSS]"。左列だけを継いで [ ] を取る
                if 'sens' not in R and L[k][:36].lstrip().startswith('['):
                    blob = ' '.join(L[x][:36].strip() for x in range(k, min(k+4, len(L))))
                    mb = re.search(r'\[([A-Z/ ,]+?)\]', blob.replace(' or ', ', '))
                    if mb: R['sens'] = [x.strip() for x in mb.group(1).replace('INS, IRS', 'INS/IRS').split(',') if x.strip()]
            i += 1; continue
        if cur is None or is_header(l): i += 1; continue
        mc = COORD.search(l)
        if mc and mc.start() < 30:
            nm, nid = point_name(L, i)
            p = {'n': nm, 'lat': dms(mc.group(1), False), 'lng': dms(mc.group(2), True)}
            if nid: p['id'] = nid
            R = routes[cur]
            if not R['pts'] or R['pts'][-1]['n'] != nm: R['pts'].append(p)
            # この行の右側 = 次の点までの区間
            rest = l[mc.end():]
            seg = {'a': nm}
            toks = list(re.finditer(r'(UNL|FL\d{2,3}|\d+(?:\.\d+)?|[↓↑])', rest))
            nums = [(t.group(1), mc.end()+t.start()) for t in toks]
            # 順番: [navaid方位/距離は後の行] 磁方位 距離 上限 MEA 矢印
            plain = [(v, c) for v, c in nums if v not in ('↓', '↑')]
            arrows = [(v, c) for v, c in nums if v in ('↓', '↑')]
            k = 0
            if k < len(plain) and re.fullmatch(r'\d{3}', plain[k][0]) and int(plain[k][0]) <= 360:
                seg['mag'] = int(plain[k][0]); k += 1
            if k < len(plain) and re.fullmatch(r'\d+(?:\.\d+)?', plain[k][0]) and float(plain[k][0]) < 400:
                seg['dist'] = float(plain[k][0]); k += 1
            if k < len(plain) and (plain[k][0] == 'UNL' or plain[k][0].startswith('FL') or
                                   (plain[k][0].isdigit() and int(plain[k][0]) >= 1000)):
                seg['up'] = plain[k][0] if not plain[k][0].isdigit() else int(plain[k][0]); k += 1
            if k < len(plain) and (plain[k][0].startswith('FL') or (plain[k][0].isdigit() and int(plain[k][0]) >= 1000)):
                seg['mea'] = plain[k][0] if not plain[k][0].isdigit() else int(plain[k][0]); k += 1
            # 矢印はこの行と、次の座標行の手前までの行から拾う
            j = i+1
            while j < len(L) and not COORD.search(L[j]) and not DESIG.match(L[j]):
                for t in re.finditer(r'[↓↑]', L[j]): arrows.append((t.group(0), t.start()))
                j += 1
            for v, c in arrows:
                key = 'odd' if (col_odd is None or abs(c-col_odd) <= abs(c-col_even)) else 'even'
                seg.setdefault(key, v)
            # 次の行: [真方位] と [MOCA]
            if i+1 < len(L):
                br = re.findall(r'\[(FL\d+|\d+(?:\.\d+)?)\]', L[i+1])
                for b in br:
                    if b.startswith('FL'): seg['moca'] = b          # MOCA が FL で書かれる区間がある(Y60 MITOP-MEBNI [FL150])
                    elif '.' in b: seg['true'] = float(b)
                    else: seg['moca'] = int(b)
                if 'DME' in L[i+1] or 'required' in L[i+1]: seg['rmk'] = L[i+1].strip()[:80]
            R['segs'].append(seg)
        i += 1
    # 区間の b を埋める(次の点)、最後の点の区間は捨てる
    for R in routes.values():
        segs = []
        for k, s in enumerate(R['segs']):
            if k+1 < len(R['pts']):
                s['b'] = R['pts'][k+1]['n']; segs.append(s)
        R['segs'] = segs
    return routes

# ── ENR 3.5.1 直行経路 ──────────────────────────────────────────────
NAV_T = r'(?:VOR/DME|VORTAC|TACAN|VOR|NDB|DME)'
TOK35 = re.compile(r'(?P<brg>\d{3})°|'
                   r'(?P<dme>[A-Z]{3})\s{0,14}(?P<dmen>\d{1,3})\s{0,3}DME\b|'
                   r'(?P<nav>[A-Z]{3})\*?\s{1,6}' + NAV_T + r'\*?|'
                   r'(?P<fix>[A-Z]{4,7})\*?(?=\s|$)|'
                   r'(?P<rmk>[(*].*$)')
R_NM = 3440.065


def _geo(a, b):
    import math
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2))
    y = math.sin(lo2-lo1)*math.cos(la2); x = math.cos(la1)*math.sin(la2) - math.sin(la1)*math.cos(la2)*math.cos(lo2-lo1)
    return d*R_NM, math.atan2(y, x)


def _dest(a, brg, nm):
    import math
    la1, lo1 = math.radians(a[0]), math.radians(a[1]); d = nm/R_NM
    la2 = math.asin(math.sin(la1)*math.cos(d) + math.cos(la1)*math.sin(d)*math.cos(brg))
    lo2 = lo1 + math.atan2(math.sin(brg)*math.sin(d)*math.cos(la1), math.cos(d) - math.sin(la1)*math.sin(la2))
    return round(math.degrees(la2), 6), round(math.degrees(lo2), 6)


# ENR 4.1 に無い飛行場の VOR/DME(各 AD 2.19 から。ENR 3.5.1 の直行経路の端点に出てくる)
# ⚠ KCE(神戸)と同じ理由: 経路用でない飛行場の施設は AD 2.19 にしか載らない。AIRAC で位置が動いたら直す
EXTRA_NAV = {
    'AKE': ('AMAKUSA',      '322848.85N', '1300939.48E'),   # RJDA
    'KGE': ('KAJIKI',       '314751.15N', '1304333.97E'),   # RJFK(鹿児島)
    'OSE': ('OSHIMA(OSE)',  '344715.87N', '1392153.46E'),   # RJTO ⚠ 大島VOR(XAC)と同じ島。名前を分ける
    'SGE': ('SAGA',         '330855.03N', '1301734.43E'),   # RJFS
    'SJE': ('SHIMOJISHIMA', '244918.96N', '1250837.70E'),   # RORS
    'TKE': ('TOKUNOSHIMA',  '274929.20N', '1285255.98E'),   # RJKN
    'TOE': ('TOYAMA',       '363907.88N', '1371128.00E'),   # RJNT
    'VCE': ('TSUSHIMA',     '341653.43N', '1292013.24E'),   # RJDT
    'YKE': ('YAKUSHIMA',    '302246.01N', '1303945.78E'),   # RJFC
    'YRE': ('YORON',        '270239.75N', '1282352.89E'),   # RORY
}


def load_points():
    """navaid(ENR 4.1)と FIX(fix.json)の座標表。navaid は ID → (名前, lat, lng)"""
    nav = {}
    js = open(os.path.join(HERE, 'navaids.gen.js'), encoding='utf-8').read()
    for a in json.loads(js[js.index('['):js.rindex(']')+1]):
        if a.get('id') and a['id'] not in nav: nav[a['id']] = a
    for k, (n, la, lo) in EXTRA_NAV.items():
        nav.setdefault(k, {'n': n, 'id': k, 'lat': dms(la[:-1], False), 'lng': dms(lo[:-1], True)})
    fx = {}
    try:
        for f in json.load(open(os.path.join(HERE, '..', 'fix.json')))['f']:
            fx.setdefault(f['n'], f)
            if f.get('id') and f['id'] in nav: nav[f['id']]['_n'] = f['n']   # navaid の表記(WAKKANAI)は FIX 表に合わせる
    except FileNotFoundError:
        print('  ⚠ fix.json が無い(先に gen_fix.py)。FIX名の直行経路は座標が引けない', file=sys.stderr)
    return nav, fx


def parse_35(L):
    nav, fx = load_points()
    routes = {}; miss = set(); nrow = 0
    def pt_of(t):
        if t['t'] == 'nav':
            a = nav.get(t['v'])
            if not a: miss.add(t['v']); return None
            return {'n': a.get('_n') or a['n'].upper(), 'id': t['v'], 'lat': a['lat'], 'lng': a['lng']}
        if t['t'] == 'fix':
            f = fx.get(t['v'])
            if not f: miss.add(t['v']); return None
            p = {'n': f['n'], 'lat': f['lat'], 'lng': f['lng']}
            if f.get('id'): p['id'] = f['id']
            return p
        # 2表記の点は表記順を揃える(往路と復路で "MZE 40DME/TGE 40DME" と "TGE 40DME/MZE 40DME" に割れて2本になった)
        nm = '/'.join(sorted([f"{t['v']} {t['d']}DME"] + ([t['alias']] if t.get('alias') else [])))
        return {'n': nm, 'dme': [t['v'], t['d']]}
    def nums(l, pat):
        return [(m.group(1), m.start()) for m in re.finditer(pat, l)]
    for i, l in enumerate(L):
        # ⚠ is_header() は行末の VOR/DME を見出し扱いするのでここでは使えない(行の大半が navaid で終わる)
        if '°' not in l or 'Bearing' in l or 'LEGEND' in l: continue
        # ⚠ 起点が FIX の経路は行頭に "(OSE VOR/DME 018° 42nm) DAIBU 018° …" と FIX の定義が括弧で付く(13行)。
        #   括弧を備考と見なすと行ごと捨ててしまい、DAIBU-KOSKA のような**SIDと航空路をつなぐ経路**が丸ごと落ちた
        l = re.sub(r'^\s*\([A-Z]{3}\s+' + NAV_T + r'[^)]*\)', lambda m: ' '*len(m.group(0)), l)
        toks = []
        for m in TOK35.finditer(l):
            k = 'dme' if m.group('dme') else m.lastgroup   # ⚠ lastgroup は dmen(数字側)になるので dme を先に見る
            if k == 'rmk': toks.append({'t': 'rmk', 'v': m.group('rmk').strip()}); break
            if k == 'brg': toks.append({'t': 'brg', 'v': int(m.group('brg')), 'c': m.start()})
            elif k == 'dme':
                # ⚠ "MZE 40DME / TGE 40DME" は同じ1点の2表記(宮崎-種子島)。'/' で繋がっていたら前の点に併合
                if toks and toks[-1]['t'] == 'dme' and '/' in l[toks[-1]['e']:m.start()]:
                    toks[-1]['alias'] = f"{m.group('dme')} {m.group('dmen')}DME"; toks[-1]['e'] = m.end(); continue   # ⚠ e を進めないと次の点まで併合する
                toks.append({'t': 'dme', 'v': m.group('dme'), 'd': int(m.group('dmen')), 'c': m.start(), 'e': m.end()})
            elif k == 'nav': toks.append({'t': 'nav', 'v': m.group('nav'), 'c': m.start()})
            elif k == 'fix': toks.append({'t': 'fix', 'v': m.group('fix'), 'c': m.start()})
        rmk = next((t['v'] for t in toks if t['t'] == 'rmk'), None)
        seq = [t for t in toks if t['t'] != 'rmk']
        pts_i = [j for j, t in enumerate(seq) if t['t'] != 'brg']
        if len(pts_i) < 2: continue
        nrow += 1
        pts = [pt_of(seq[j]) for j in pts_i]
        if any(p is None for p in pts): continue
        # DME フィックス: 経路の直線上で、その navaid から n nm の点
        known = [p for p in pts if 'lat' in p]
        if len(known) < 2: miss.add(' '.join(p['n'] for p in pts)); continue
        A, Z = known[0], known[-1]
        for p in pts:
            if 'dme' in p:
                nid, d = p['dme']; X = nav.get(nid)
                if not X: miss.add(nid); break
                _, bAZ = _geo((A['lat'], A['lng']), (Z['lat'], Z['lng']))
                _, bZA = _geo((Z['lat'], Z['lng']), (A['lat'], A['lng']))
                if nid == A.get('id'): p['lat'], p['lng'] = _dest((A['lat'], A['lng']), bAZ, d)
                elif nid == Z.get('id'): p['lat'], p['lng'] = _dest((Z['lat'], Z['lng']), bZA, d)
                else:   # 途中の navaid から: A→Z 上を走査して距離 d に一番近い点
                    dAZ, _ = _geo((A['lat'], A['lng']), (Z['lat'], Z['lng'])); best = None
                    for k in range(0, 201):
                        q = _dest((A['lat'], A['lng']), bAZ, dAZ*k/200)
                        e = abs(_geo(q, (X['lat'], X['lng']))[0] - d)
                        if best is None or e < best[0]: best = (e, q)
                    p['lat'], p['lng'] = best[1]
                del p['dme']
        if any('lat' not in p for p in pts): continue
        # 磁方位: 点の直後の方位はその点からの出発方位、点の直前(1空白で隣接)はその点から戻る方位
        out_b = {}; back_b = {}
        for j, t in enumerate(seq):
            if t['t'] != 'brg': continue
            prv = next((seq[k] for k in range(j-1, -1, -1) if seq[k]['t'] != 'brg'), None)
            nxt = next((seq[k] for k in range(j+1, len(seq)) if seq[k]['t'] != 'brg'), None)
            near_next = nxt is not None and nxt['c'] - (t['c']+4) <= 2
            if near_next: back_b[pts_i.index(seq.index(nxt))] = t['v']
            elif prv is not None: out_b[pts_i.index(seq.index(prv))] = t['v']
        # 距離(上の行)と MEA(下の行)を桁で区間に割り当てる
        up = L[i-1] if i > 0 else ''; dn = L[i+1] if i+1 < len(L) else ''
        dn2 = L[i+2] if i+2 < len(L) else ''
        dists = nums(up, r'(\d+(?:\.\d+)?)\s*nm')
        meas = nums(dn, r'(FL\d{2,3}|\d{4,5})(?!\d|nm)')
        cols = [seq[j]['c'] for j in pts_i]
        segs = []
        for k in range(len(pts)-1):
            sg = {'a': pts[k]['n'], 'b': pts[k+1]['n']}
            lo, hi = cols[k], cols[k+1]
            dd = [v for v, c in dists if lo <= c+2 < hi] or ([dists[k][0]] if len(dists) == len(pts)-1 else [])
            mm = [v for v, c in meas if lo <= c+2 < hi] or ([meas[k][0]] if len(meas) == len(pts)-1 else [])
            if dd: sg['dist'] = float(dd[0])
            if mm:
                vals = [int(v) if v.isdigit() else v for v in mm]
                sg['mea'] = max(vals, key=lambda v: (v if isinstance(v, int) else int(v[2:])*100))
                if len(vals) > 1:   # "← 6000 5000 →" 方向別。その区間の桁範囲だけ切り出す
                    span = dn[max(0, lo-2):hi+2]
                    sg['rmk'] = '方向別MEA ' + re.sub(r'\s+', ' ', span).strip()
            if k in out_b: sg['mag'] = out_b[k]
            elif k+1 in back_b: sg['rmag'] = back_b[k+1]
            segs.append(sg)
        # 直行経路は1行=1直線なので、途中の区間には行の出発方位/戻り方位をそのまま継ぐ(inh に印)
        for k, sg in enumerate(segs):
            if 'mag' not in sg and 'rmag' not in sg:
                if out_b: sg['mag'] = out_b[min(out_b)]; sg['inh'] = ['mag']
                elif back_b: sg['rmag'] = back_b[max(back_b)]; sg['inh'] = ['rmag']
        if rmk: segs[0]['rmk'] = (segs[0].get('rmk', '') + ' ' + rmk).strip()
        if re.search(r'COP:|MCA', dn2): segs[0]['rmk'] = (segs[0].get('rmk', '') + ' ' + dn2.strip()[:80]).strip()
        names = [p['n'] for p in pts]
        key = tuple(names) if names[0] <= names[-1] else tuple(reversed(names))
        if key in routes:
            R = routes[key]
            if tuple(names) != key:            # 逆向きの再掲: 戻り方位を補う
                for sg in segs:
                    for t in R['segs']:
                        if t['a'] == sg['b'] and t['b'] == sg['a']:
                            if 'mag' in sg: t.setdefault('rmag', sg['mag'])
                            if 'rmag' in sg: t.setdefault('mag', sg['rmag'])
                            if 'mea' in sg and 'mea' not in t: t['mea'] = sg['mea']
            continue
        if tuple(names) != key: pts = list(reversed(pts)); segs = [dict(sg, a=sg['b'], b=sg['a'], mag=sg.get('rmag'), rmag=sg.get('mag')) for sg in reversed(segs)]
        for sg in segs:
            for kk in ('mag', 'rmag'):
                if sg.get(kk) is None: sg.pop(kk, None)
        short = lambda p: p.get('id') or p['n']
        routes[key] = {'n': f"{short(pts[0])}-{short(pts[-1])}", 'pts': pts, 'segs': segs}
    if miss: print(f'  ⚠ 3.5.1 座標を引けない点 {len(miss)}: {sorted(miss)[:15]}', file=sys.stderr)
    print(f'  ENR 3.5.1: 行 {nrow} → 経路 {len(routes)}', file=sys.stderr)
    return routes


def main():
    pdf = find_pdf()
    if not pdf: print('ENRのPDFが無い', file=sys.stderr); sys.exit(1)
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
    L31 = cut(txt, r'ENR 3\.1 LOWER ATS ROUTES', r'ENR 3\.2 UPPER ATS ROUTES')
    L33 = cut(txt, r'ENR 3\.3 RNAV', r'ENR 3\.4 HELICOPTER')
    L35 = cut(txt, r'ENR 3\.5 OTHER ROUTES', r'2\. Oceanic Transition routes')
    r31 = parse_31(L31); r33 = parse_33(L33); r35 = parse_35(L35)
    out = ([dict(v, k='LOW') for v in r31.values()] + [dict(v, k='RNAV') for v in r33.values()]
           + [dict(v, k='DCT') for v in r35.values()])
    eff = os.path.basename(os.path.dirname(pdf))
    dst = os.path.join(HERE, '..', 'awy.json')
    json.dump({'eff': eff, 'src': 'AIP Japan ENR 3.1 / 3.3 / 3.5.1', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    def stat(rs):
        np_ = sum(len(r['pts']) for r in rs); ns = sum(len(r['segs']) for r in rs)
        nd = sum(1 for r in rs for s in r['segs'] if 'dist' in s)
        nm = sum(1 for r in rs for s in r['segs'] if 'mea' in s)
        return f'{len(rs)}本 {np_}点 {ns}区間 (dist有 {nd} / MEA有 {nm})'
    print('  ENR 3.1:', stat(list(r31.values())), file=sys.stderr)
    print('  ENR 3.3:', stat(list(r33.values())), file=sys.stderr)
    print('  ENR 3.5.1:', stat(list(r35.values())), file=sys.stderr)
    print(f'{len(out)} 本 → awy.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')


if __name__ == '__main__':
    main()
