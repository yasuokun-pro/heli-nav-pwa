#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飛行方式一覧 生成 (proc.json)
============================
出典: AIP Japan 各飛行場 **AD 2.24 CHARTS RELATED TO AN AERODROME** の索引ページ。
SID / STAR / 計器進入(IAC) の**名前と種別だけ**を取る。形(経路)は図なので取らない。

使い方:
  python3 tools/gen_proc.py           # proc.json を出力

⚠ 索引の書式(2026-09 に確認・113空港)
  - "Standard Departure Chart - Instrument (VAMOS-RNAV)"  → SID。名前に RNAV が入れば RNAV SID
  - "Standard Arrival Chart - Instrument (OSHIMA-1A/1K/2C-RNAV)" → STAR
  - "Instrument Approach Chart (ILS Z RWY34L)" → IAC。先頭語が種別:
      ILS 165 / RNP 217 / VOR 147 / TACAN 60 / LOC 44 / LDA 8 / RNAV 6 / HI-ILS 5 /
      RNAV(GPS) 4 / VOR/DME 2 / HI-VOR 2 / HI-TACAN 2 / GLS 2 (全国の枚数)
  - ⚠ 図そのもの(DA/MDA/RVR)は本文レイヤが文字化け混じりで取れない(RJTT AD2-259 で確認)。
    ミニマは別途、手で表を持つか諦める
"""
import os, re, sys, json, glob, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
KIND = [('Standard Departure Chart', 'SID'), ('Standard Arrival Chart', 'STAR'),
        ('Instrument Approach Chart', 'IAC')]
TYP = re.compile(r'^(HI-ILS|HI-VOR|HI-TACAN|ILS|LOC|LDA|VOR/DME|VOR|TACAN|NDB|RNP|RNAV\(GPS\)|RNAV|GLS)\b')


def pdfs():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine/*.pdf',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine/*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: return f
    return []


def parse_one(pdf):
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
    icao = os.path.basename(pdf)[:4]
    L = txt.split('\n'); out = []; on = False
    # ⚠ 長い名前は索引でも2行に折れる("(OSHIMA, AKSEL,\n AROSA-2H-RNAV)")。閉じ括弧が無ければ次行を継ぐ
    J = []
    for l in L:
        if J and '(' in J[-1] and ')' not in J[-1] and any(k in J[-1] for k, _ in KIND):
            J[-1] = J[-1].rstrip() + ' ' + l.strip()
        else: J.append(l)
    L = J
    gap = 0
    for l in L:
        if 'AD 2.24' in l and 'CHARTS RELATED' in l: on = True; continue
        if not on: continue
        # ⚠ 索引は2ページにまたがることがある(RJTTなど)。ページの脚注で切らず、
        #   一覧が始まったあと該当行が15行続けて無くなったら終わりとみなす
        if re.search(r'AD 2\.25', l) and out: break
        if any(key in l for key, _ in KIND): gap = 0
        elif out:
            gap += 1
            if gap > 15: break
        for key, k in KIND:
            if key in l:
                # ⚠ 末尾に '*'(脚注印)が付く行がある(RJCC は 34枚中 20枚)。閉じ括弧の後の * は無視
                m = re.search(r'\((.*)\)\s*\**\s*$', l.strip())
                if m: name = m.group(1).strip()
                else:
                    # ⚠ 自衛隊系(築城・美保・小松島・三沢・防府北など)は方式名を索引に書かず
                    #   "Standard Departure Chart - Instrument-1" のように枚数だけ。名前は図にしかない
                    ms = re.search(key + r'\s*-?\s*Instrument\s*-?\s*(\d)?\s*$', l.strip())
                    if not ms and not re.search(key + r'\s*$', l.strip()): continue
                    name = ('#' + ms.group(1)) if ms and ms.group(1) else '#'
                rec = {'icao': icao, 'k': k, 'n': name}
                if name.startswith('#'): rec['nn'] = 1          # 索引に名前が無い(図参照)
                if 'RNAV' in name or 'RNP' in name: rec['rnav'] = 1
                if k == 'IAC':
                    mt = TYP.match(name)
                    if mt: rec['typ'] = mt.group(1)
                    mr = re.search(r'RWY\s*(\d{2}[LRC]?)', name)
                    if mr: rec['rwy'] = mr.group(1)
                    if 'CAT II' in name or 'CAT III' in name: rec['cat'] = 'II/III'
                    if 'HELI' in name.upper() or 'COPTER' in name.upper(): rec['heli'] = 1
                out.append(rec)
    return out


def main():
    fs = pdfs()
    if not fs: print('AD2のPDFが無い', file=sys.stderr); sys.exit(1)
    out = []
    for f in fs: out += parse_one(f)
    eff = os.path.basename(os.path.dirname(os.path.dirname(fs[0])))
    dst = os.path.join(HERE, '..', 'proc.json')
    json.dump({'eff': eff, 'src': 'AIP Japan AD 2.24 索引', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    ap = len(set(x['icao'] for x in out))
    c = {k: sum(1 for x in out if x['k'] == k) for _, k in KIND}
    print(f"{ap} 空港 SID {c['SID']} / STAR {c['STAR']} / IAC {c['IAC']} → proc.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}")


if __name__ == '__main__':
    main()
