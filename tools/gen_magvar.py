#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
磁気偏差(西偏)の近似係数 生成
==============================
各飛行場 AD2 の「AD 2.2 MAG VAR」に載っている実測値を集め、
緯度経度の2次多項式で最小二乗フィットして係数を出す。
index.html の MAGV_C に手で貼り替える(数値6個だけなので自動埋め込みはしない)。

    varW ≒ c0 + c1*x + c2*y + c3*x² + c4*xy + c5*y²
        x = 経度-137.0 , y = 緯度-36.0

使い方: python3 tools/gen_magvar.py
AIRAC更新で偏差がずれてきたら再実行して係数を更新する(年あたり数分角ずつ動く)。
"""
import re, glob, os, json, subprocess, sys

def dms(s):
    m = re.match(r'(\d{2,3})(\d{2})(\d{2}(?:\.\d+)?)', s)
    return float(m.group(1)) + float(m.group(2))/60 + float(m.group(3))/3600

def main():
    base = None
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine'):
        d = sorted(glob.glob(os.path.expanduser(pat)))
        if d: base = d[-1]; break
    if not base:
        print('AD2_Combine が見つかりません', file=sys.stderr); sys.exit(1)
    pts = []
    for pdf in sorted(glob.glob(base + '/*.pdf')):
        icao = os.path.basename(pdf).split('__')[0]
        txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
        a = re.search(r'ARP coordinates.*?(\d{6}(?:\.\d+)?)N[ /]*(\d{7}(?:\.\d+)?)E', txt)
        v = re.search(r'MAG VAR[^\n]*?(\d+(?:\.\d+)?)\s*°?\s*([WE])', txt)
        if a and v:
            pts.append((icao, dms(a.group(1)), dms(a.group(2)),
                        float(v.group(1)) * (1 if v.group(2) == 'W' else -1)))
    if len(pts) < 20:
        print(f'サンプルが少なすぎます({len(pts)}件)', file=sys.stderr); sys.exit(1)
    try:
        import numpy as np
    except ImportError:
        print('numpy が必要です: python3 -m pip install --user numpy', file=sys.stderr); sys.exit(1)
    A = np.array([[1, lo-137.0, la-36.0, (lo-137.0)**2, (lo-137.0)*(la-36.0), (la-36.0)**2]
                  for _, la, lo, _ in pts])
    b = np.array([v for *_, v in pts])
    c, *_ = np.linalg.lstsq(A, b, rcond=None)
    err = A @ c - b
    print(f'{len(pts)} 空港でフィット')
    print('最大誤差 %.3f° / RMS %.3f°' % (abs(err).max(), float((err**2).mean()**.5)))
    print('const MAGV_C=[' + ','.join('%.6f' % v for v in c) + '];')

if __name__ == '__main__': main()
