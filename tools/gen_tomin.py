#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
離陸最低気象条件(TAKE-OFF MINIMA) 抜粋 (tomin.json)
==================================================
出典: AIP Japan 各飛行場 **AD 2.22 FLIGHT PROCEDURES** の "TAKE OFF MINIMA" の表(109空港)。
表は RWY×航空機分類×灯火条件の RVR/VIS で、LVP時の *印など構造が複雑なので**数値に解釈せず原文のまま**持つ。
IFR計画の気象欄に <pre> で出して、判断はパイロットに任せる(社内ミニマは各自が把握している)。

使い方: python3 tools/gen_tomin.py   # tomin.json
⚠ 自衛隊・米軍の飛行場(立川・館山・横田など18空港)には無い → "AIPに記載なし"
"""
import os, re, sys, json, glob, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))

def pdfs():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine/*.pdf',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine/*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f:
            # ⚠ 日付フォルダが複数あると全AIRACのPDFが混ざる(2026-09 に踏んだ)。最新の日付フォルダだけ
            latest = max(os.path.basename(os.path.dirname(os.path.dirname(x))) for x in f)
            return [x for x in f if os.path.basename(os.path.dirname(os.path.dirname(x))) == latest]
    return []

def extract(txt):
    L = txt.split('\n'); out = []; on = False
    for i, l in enumerate(L):
        if not on:
            if re.search(r'AD 2\.22', l) or on: pass
            if re.search(r'^\s*\d?\.?\s*TAKE[ -]?OFF MINIMA\s*$', l, re.I): on = True; continue
            continue
        # 次の項目("2. …" や "AD 2.23")で終わり。ページの脚注・見出しは飛ばす
        if re.search(r'^\s*\d+\.\s+\S', l) or 'AD 2.23' in l: break
        if re.search(r'Civil Aviation Bureau|^\s*AIP Japan|AD2-\d+|FLIGHT PROCEDURES', l): continue
        out.append(l.rstrip())
    # 前後の空行を落とし、連続する空行は1つに
    res = []
    for l in out:
        if not l.strip() and (not res or not res[-1].strip()): continue
        res.append(l)
    while res and not res[-1].strip(): res.pop()
    return '\n'.join(res)

def main():
    fs = pdfs()
    if not fs: print('AD2のPDFが無い', file=sys.stderr); sys.exit(1)
    out = {}
    for f in fs:
        icao = os.path.basename(f)[:4]
        txt = subprocess.run(['pdftotext', '-layout', f, '-'], capture_output=True, text=True).stdout
        t = extract(txt)
        if t: out[icao] = t
    eff = os.path.basename(os.path.dirname(os.path.dirname(fs[0])))
    dst = os.path.join(HERE, '..', 'tomin.json')
    json.dump({'eff': eff, 'src': 'AIP Japan AD 2.22 TAKE-OFF MINIMA(原文抜粋)', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 空港 → tomin.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')
    for k in ('RJTT', 'RJNA', 'RJTC', 'RJGG'):
        print('##', k, '\n' + (out.get(k) or 'なし')[:700])

if __name__ == '__main__':
    main()
