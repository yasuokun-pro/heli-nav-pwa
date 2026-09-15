#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ヘリポート・臨時離着陸場レイヤー 生成 (helipad.json)
====================================================
出典: 国土数値情報「ヘリポート」(国土交通省) **N11-13**(平成25年9月現在)
      https://nlftp.mlit.go.jp/ksj/  ※利用規約により**出典明示が必要**

中身: 公共用・非公共用ヘリポートに加えて、**都道府県の地域防災計画に載っている
      場外離着陸場・緊急離着陸場**(学校のグラウンド・公園・河川敷など)。
      各県の防災計画のPDFを集めなくても、これ1つで全国分が座標つきで揃う。

⚠ 2013年のデータで更新されていない。閉鎖・移転しているものがある前提で「参考」として出す。
⚠ 座標は施設の**おおよその中心**。進入方向・障害物・使用条件は一切入っていない。
⚠ ここに載っていても**勝手に降りてよい場所ではない**(管理者の許可・航空法79条の場外許可が要る)。

使い方:
  python3 tools/gen_helipad.py            # ダウンロードして生成
  python3 tools/gen_helipad.py --cache    # ダウンロード済みから再生成
"""
import json, os, re, sys, zipfile, urllib.request, collections

HERE = os.path.dirname(os.path.abspath(__file__))
VER = 'N11-13'
BASE = 'https://nlftp.mlit.go.jp/ksj/gml/data/N11/%s/%s_%02d.zip'
CACHE = '/tmp/helipad_ksj'
# 航空法上の分類(N11_002)。コード表は KsjTmplt-N11 の「航空法分類コード」
CCC = {'1': '公共用', '2': '非公共用', '3': '場外・緊急離着陸場'}


def fetch(n):
    os.makedirs(CACHE, exist_ok=True)
    p = f'{CACHE}/{n:02d}.zip'
    if not os.path.exists(p):
        if '--cache' in sys.argv: return None
        url = BASE % (VER, VER, n)
        req = urllib.request.Request(url, headers={'User-Agent': 'heli-nav-pwa/1.0'})
        with urllib.request.urlopen(req, timeout=180) as r: open(p, 'wb').write(r.read())
    return p


def parse(path):
    with zipfile.ZipFile(path) as z:
        nm = [x for x in z.namelist() if x.endswith('.xml') and 'META' not in x]
        if not nm: return []
        x = z.read(nm[0]).decode('utf-8', 'replace')
    # gml:Point の id → 座標
    pts = {}
    for m in re.finditer(r'<gml:Point gml:id="([^"]+)">.*?<gml:pos>([\d.]+)\s+([\d.]+)</gml:pos>', x, re.S):
        pts[m.group(1)] = (round(float(m.group(2)), 6), round(float(m.group(3)), 6))
    out = []
    for m in re.finditer(r'<ksj:Heliport.*?</ksj:Heliport>', x, re.S):
        b = m.group(0)
        g = lambda t: (re.search(r'<ksj:%s[^>]*>(.*?)</ksj:%s>' % (t, t), b, re.S) or [None, ''])[1].strip()
        ref = re.search(r'<ksj:loc xlink:href="#([^"]+)"', b)
        if not ref or ref.group(1) not in pts: continue
        lat, lng = pts[ref.group(1)]
        r = {'n': g('noh'), 'lat': lat, 'lng': lng}
        c = g('ccc')
        if c in CCC: r['c'] = c
        for k, t in (('a', 'ads'), ('m', 'adn'), ('s', 'sor'), ('k', 'nor')):
            v = g(t)
            if v and v != '不明': r[k] = v
        out.append(r)
    return out


def main():
    all_ = []
    for n in range(1, 48):
        p = fetch(n)
        if not p: continue
        rows = parse(p)
        all_ += rows
        print(f'  {n:02d}: {len(rows)}', end='\n' if n % 8 == 0 else '  ', file=sys.stderr)
    # 同じ場所・同じ名前の重複を落とす
    seen, out = set(), []
    for r in all_:
        k = (r['n'], round(r['lat'], 4), round(r['lng'], 4))
        if k in seen: continue
        seen.add(k); out.append(r)
    # 種別と管理者は同じ文字列の繰り返しが多い(235種/3421者)。番号に置き換えて軽くする
    kinds, mgrs = [], []
    ki, mi = {}, {}
    for r in out:
        if r.get('k'):
            if r['k'] not in ki: ki[r['k']] = len(kinds); kinds.append(r['k'])
            r['k'] = ki[r['k']]
        if r.get('m'):
            if r['m'] not in mi: mi[r['m']] = len(mgrs); mgrs.append(r['m'])
            r['m'] = mi[r['m']]
    dst = os.path.join(HERE, '..', 'helipad.json')
    json.dump({'ver': VER, 'src': '国土数値情報(ヘリポート) 国土交通省 N11-13(平成25年)',
               'kinds': kinds, 'mgrs': mgrs, 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'\n{len(out)} 箇所 → helipad.json ({os.path.getsize(dst)/1024:.0f}KB)')
    print('  分類:', collections.Counter(CCC.get(r.get('c'), '不明') for r in out))
    print('  種別(上位):', collections.Counter(r.get('k', '') for r in out).most_common(6))


if __name__ == '__main__':
    main()
