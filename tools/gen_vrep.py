#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VFR 位置通報点(Visual REP)を AIP AD 2.24 の Visual REP の図の表から起こす → vrep.json
=====================================================================================
・各飛行場の「Other Chart (Visual REP)」の下の表に「呼び名 / ARP からの真方位・距離(036°T / 5.3NM)/ 備考」がある。
  位置は ad.json の ARP からその真方位・距離で計算する(図から読み取らない)
・⚠ 和名は図のフォントの割り当てが崩れていて pdftotext でも PyMuPDF でも化ける。英名(通報で使う呼び名)と英文の備考だけ使う
・⚠ 同じ飛行場の図が有効日違いで複数入ることがある。発行日以前で一番新しいものを使う
・AD3(ヘリポート)は本体の PDF の中の Visual REP のページを読む(東京ヘリポート・奈多)
・表の無い図(関西・静岡・高知)は対象外
出力: vrep.json {eff, f:[{icao, n, rmk, brg, nm, lat, lng}]}
使い方: python3 tools/gen_vrep.py [--airac 20261001]
"""
import os, re, sys, json, glob, math, subprocess

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
AIP = os.path.join(ROOT, 'aip', '1_AIP (PDF)')
BD = re.compile(r'(\d{3})\s*°\s*T?\s*/\s*(\d+(?:\.\d+)?)\s*NM')
R_NM = 3440.065


def dest(lat, lng, brg, nm):
    d, b, p1, l1 = nm / R_NM, math.radians(brg), math.radians(lat), math.radians(lng)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return round(math.degrees(p2), 6), round(math.degrees(l2), 6)


def charts(issue):
    """飛行場ごとに Visual REP の図を1つ(ファイル名の日付 ≤ 発行日の最新)"""
    by = {}
    for f in glob.glob(os.path.join(AIP, issue, 'AD2_Separate', '*', '*')):
        if not re.search(r'visual rep', os.path.basename(f), re.I): continue
        ic = os.path.basename(os.path.dirname(f))[:4]
        m = re.search(r'_(\d{8})\.pdf$', f)
        by.setdefault(ic, []).append((m.group(1) if m else '0', f))
    out = {}
    for ic, v in by.items():
        v.sort(); ok = [x for x in v if x[0] <= issue]
        out[ic] = (ok[-1] if ok else v[0])[1]
    return out


def fix(line):
    """⚠ 英名の一部が U+3EC0〜U+3F7F に化けている(「㼀㼍㼗㼑㼟㼔㼕㼙㼍」= Takeshima)。ord-0x3EAC で ASCII に戻る。
    行頭の 䚷(U+46B7)は全角空白の化け"""
    return ''.join(chr(ord(c) - 0x3EAC) if 0x3EC0 <= ord(c) <= 0x3F7F else (' ' if c == '\u46b7' else c) for c in line)


def parse(path, page=None):
    t = subprocess.run(['pdftotext'] + (['-f', str(page), '-l', str(page)] if page else []) + ['-layout', path, '-'],
                       capture_output=True, text=True).stdout
    L = [fix(l) for l in t.split('\n')]
    hi = next((i for i, l in enumerate(L) if 'Call sign' in l and 'Remarks' in l), None)
    if hi is None: return []
    c_call, c_rmk = L[hi].index('Call sign'), L[hi].index('Remarks')

    def segs(j):
        out = []
        for mm in re.finditer(r'\S(?:.*?\S)?(?=\s{2,}|$)', L[j]):
            s, col = mm.group(0), mm.start()
            if not re.fullmatch(r'[ -~]+', s) or not re.search(r'[A-Za-z0-9]', s) or BD.search(s) or s.startswith('CHANGE'): continue
            out.append((col, s))
        return out
    rows, used, idx = [], set(), [i for i in range(hi + 1, len(L)) if BD.search(L[i])]
    for k, i in enumerate(idx):
        m = BD.search(L[i]); stop = idx[k + 1] if k + 1 < len(idx) else min(len(L), i + 9)
        name = rmk = ''; nline = None
        # ⚠ 名前と和文の備考が距離の行の**前の行**に並ぶ表がある(RORS・RORT)。前の行に英名と和文が同居していればそれを採る
        #   (ふつうの表では前の行は前の点の英名・英文の備考だけの行なので当たらない)
        if i - 1 > hi and i - 1 not in used and re.search(r'[^\x00-\x7f]', L[i - 1]):
            c = [s for col, s in segs(i - 1) if abs(col - c_call) <= 14]
            if c: name, nline = c[0], i - 1
        # ⚠ 表の途中に縦書きの注記(CHANGE …)が挟まって名前の行が下にずれることがある(成田 Yamada)
        for j in range(i, min(stop, i + 9)):
            if nline is not None and nline < i and j > i and any(abs(col - c_call) <= 14 for col, s in segs(j)): break   # 次の点の名前の行
            for col, s in segs(j):
                if abs(col - c_call) <= 14 and not name and re.search(r'[A-Za-z]', s): name, nline = s, j
                elif col >= c_rmk - 12 and not rmk: rmk = s
        if not name:
            # ⚠ 名前が距離の行より前に来る表がある(RORS の 9NM NW)。前の行のうち、前の点が使っていないものを見る
            for j in (i - 1, i - 2):
                if j > hi and j not in used:
                    c = [s for col, s in segs(j) if abs(col - c_call) <= 14]
                    if c: name, nline = c[0], j; break
        if name:
            used.add(nline)
            rows.append({'n': name, 'rmk': rmk, 'brg': int(m.group(1)), 'nm': float(m.group(2))})
    return rows


def main():
    issue = sys.argv[sys.argv.index('--airac') + 1] if '--airac' in sys.argv else sorted(os.listdir(AIP))[-1]
    AD = {a['icao']: a for a in json.load(open(os.path.join(ROOT, 'ad.json')))['f']}
    out, none, noarp = [], [], []
    jobs = [(ic, f, None) for ic, f in charts(issue).items()]
    # AD3(東京ヘリポート・奈多など)は本体の PDF の中に Visual REP のページがある
    for f in glob.glob(os.path.join(AIP, issue, 'AD3', '*.pdf')):
        ic = os.path.basename(f)[:4]
        n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', f], capture_output=True, text=True).stdout).group(1))
        for p in range(1, n + 1):
            tx = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-layout', f, '-'], capture_output=True, text=True).stdout
            if 'Call sign' in tx and BD.search(tx): jobs.append((ic, f, p))
    for ic, f, pg in sorted(jobs, key=lambda x: x[0]):
        rows = parse(f, pg)
        if not rows: none.append(ic); continue
        a = AD.get(ic)
        if not a: noarp.append(ic); continue
        for r in rows:
            r['lat'], r['lng'] = dest(a['lat'], a['lng'], r['brg'], r['nm'])
            out.append(dict(icao=ic, **r))
    J = {'eff': issue, 'src': 'AIP Japan AD 2.24 Visual REP(ARP からの真方位・距離で計算)', 'f': out}
    json.dump(J, open(os.path.join(ROOT, 'vrep.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 点 / {len(set(x["icao"] for x in out))} 飛行場 → vrep.json  AIRAC:{issue}')
    if none: print('  表が読めない:', none)
    if noarp: print('  ARP が無い:', noarp)


if __name__ == '__main__':
    main()
