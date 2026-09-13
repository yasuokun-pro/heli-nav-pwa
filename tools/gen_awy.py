#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空路 生成 (awy.json)
======================
出典: AIP Japan **ENR 3.1 LOWER ATS ROUTES**(A/B/G/R/V/W) と **ENR 3.3 RNAV ROUTES**(Y/Z)

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


def main():
    pdf = find_pdf()
    if not pdf: print('ENRのPDFが無い', file=sys.stderr); sys.exit(1)
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
    L31 = cut(txt, r'ENR 3\.1 LOWER ATS ROUTES', r'ENR 3\.2 UPPER ATS ROUTES')
    L33 = cut(txt, r'ENR 3\.3 RNAV', r'ENR 3\.4 HELICOPTER')
    r31 = parse_31(L31); r33 = parse_33(L33)
    out = [dict(v, k='LOW') for v in r31.values()] + [dict(v, k='RNAV') for v in r33.values()]
    eff = os.path.basename(os.path.dirname(pdf))
    dst = os.path.join(HERE, '..', 'awy.json')
    json.dump({'eff': eff, 'src': 'AIP Japan ENR 3.1 / 3.3', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    def stat(rs):
        np_ = sum(len(r['pts']) for r in rs); ns = sum(len(r['segs']) for r in rs)
        nd = sum(1 for r in rs for s in r['segs'] if 'dist' in s)
        nm = sum(1 for r in rs for s in r['segs'] if 'mea' in s)
        return f'{len(rs)}本 {np_}点 {ns}区間 (dist有 {nd} / MEA有 {nm})'
    print('  ENR 3.1:', stat(list(r31.values())), file=sys.stderr)
    print('  ENR 3.3:', stat(list(r33.values())), file=sys.stderr)
    print(f'{len(out)} 本 → awy.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')


if __name__ == '__main__':
    main()
