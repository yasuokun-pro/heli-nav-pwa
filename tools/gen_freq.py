#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飛行場の通信周波数 生成 (AD_FREQ)
==================================
各飛行場 AD2 の「AD 2.18 ATS COMMUNICATION FACILITIES」
(ヘリポートは AD3 の「AD 3.17」)からVHF周波数を抽出する。
ログ表のIDENT/FREQ欄を自動で埋めるために使う。

出力: tools/ad_freq.json  {"RJTT":{"TWR":"118.1","GND":"118.225",...},...}
使い方: python3 tools/gen_freq.py [--splice]
"""
import re, glob, os, json, subprocess, sys

def latest(pat):
    d = sorted(glob.glob(os.path.expanduser(pat)))
    return d[-1] if d else None

# 種別の優先順(ログ欄には TWR→RDO→APP の順で入れたいので、この順で保持)
KEYS = [('TWR', r'\bTWR\b|Tower'), ('RDO', r'\bAFIS\b|\bRADIO\b|Radio\b|A/G'),
        ('APP', r'\bAPP\b|Approach'), ('DEP', r'\bDEP\b|Departure'),
        ('TCA', r'\bTCA\b'), ('GND', r'\bGND\b|Ground'), ('ATIS', r'\bATIS\b')]

def scan(pdf, sec_re):
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
    m = re.search(sec_re, txt, re.S)
    if not m: return {}
    rec = {}
    for ln in m.group(1).split('\n'):
        # 航空VHFは118.000-136.975。130MHz台のA/G等も拾えるよう全域を対象にする
        f = [x for x in re.findall(r'\b(1[123][0-9]\.[0-9]{1,3})\s*MHz', ln)
             if 118.0 <= float(x) <= 136.975]
        if not f: continue
        for key, pat in KEYS:
            if re.search(pat, ln, re.I) and key not in rec:
                rec[key] = f[0]; break
    return rec

def main():
    base = None
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine'):
        base = latest(pat)
        if base: break
    if not base:
        print('AD2_Combine が見つかりません', file=sys.stderr); sys.exit(1)
    out = {}
    for pdf in sorted(glob.glob(base + '/*.pdf')):
        icao = os.path.basename(pdf).split('__')[0]
        rec = scan(pdf, r'AD 2\.18 ATS COMMUNICATION FACILITIES(.*?)AD 2\.19')
        if rec: out[icao] = rec
    # AD3(ヘリポート)は項番が AD 3.17
    ad3 = base.replace('AD2_Combine', 'AD3')
    for pdf in sorted(glob.glob(ad3 + '/*.pdf')):
        icao = os.path.basename(pdf).split('__')[0]
        rec = scan(pdf, r'AD 3\.17 ATS COMMUNICATION FACILITIES(.*?)AD 3\.18')
        if rec: out.setdefault(icao, rec)
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, 'ad_freq.json')
    json.dump(out, open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 空港 → ad_freq.json')
    if '--splice' in sys.argv:
        idx = os.path.join(here, '..', 'index.html'); h = open(idx).read()
        js = 'const AD_FREQ=' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';'
        a, b = '/*ADFREQ_GEN_START*/', '/*ADFREQ_GEN_END*/'
        i, j = h.index(a), h.index(b)
        h = h[:i+len(a)] + '\n' + js + '\n' + h[j:]
        open(idx, 'w').write(h); print('spliced into index.html')

if __name__ == '__main__': main()
