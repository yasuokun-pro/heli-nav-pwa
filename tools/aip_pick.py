# -*- coding: utf-8 -*-
"""
AD2/AD3 の PDF を「飛行場ごとに1つ」選ぶ
========================================
⚠ 1つの発行(日付フォルダ)に、同じ飛行場の AD2 が**有効日の違う版で複数**入っていることがある。
  20261001 版: RJAH__20260709(今)と RJAH__20261025(10/25 から)/ 20261029 版: RJOA__20260903 と RJOA__20261101。
  全部読むと方式・周波数が二重になり(proc.json で百里が 46件=23×2 だった)、後勝ちだと**未来の版**が出る。
⚠ 日付フォルダの PDF は「フォルダの日付の時点で有効な AIP」(ページの EFF の最大がフォルダの日付と一致)。
  なので選ぶのは **ファイル名の日付 ≤ フォルダの日付 のうち一番新しいもの**。無ければ一番古いもの
"""
import os, re


def issue_of(path):
    """…/1_AIP (PDF)/20261029/AD2_Combine/RJAA__20261029.pdf → '20261029'"""
    m = re.search(r'/(\d{8})/AD[23]', path.replace(os.sep, '/'))
    return m.group(1) if m else '99999999'


def pick(files):
    by = {}
    for f in files:
        b = os.path.basename(f)
        icao = b.split('__')[0].split('_')[0]
        m = re.search(r'__(\d{8})', b)
        by.setdefault(icao, []).append((m.group(1) if m else '00000000', f))
    out = []
    for icao, v in sorted(by.items()):
        v.sort()
        iss = issue_of(v[0][1])
        ok = [x for x in v if x[0] <= iss]
        out.append((ok[-1] if ok else v[0])[1])
    return out
