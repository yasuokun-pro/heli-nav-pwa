#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMOC(国際気象海洋)のMETARページへの飛行場別リンク表 生成
==========================================================
NOAA(aviationweather.gov)は**自衛隊単独の飛行場のMETARを配信していない**
(立川・入間・厚木・木更津・館山・宇都宮・下総・小牧・浜松など)。
これらは気象庁の**国内配信**にはあるが国際交換に載らないため、
無料で機械取得できる経路が無い。

SWIMの気象情報は個人では契約できず、気象業務支援センターの配信は月2万円台。
IMOCのページをスクレイピングするのはライセンス外の再配信になるので行わない。
→ **先方のページを開くリンクを出す**のが現実的で、規約上も問題がない。

URLの形: https://www.imoc.co.jp/SmartPhone/d/metar.php?Lang=Jpn&Area=<地域>&Port=<ICAO>
  Area は必須。0=北海道 1=東北 2=関東 3=伊豆諸島 4=中部 5=近畿
        6=中国 7=四国 8=北九州 9=南九州 10=沖縄

出力: tools/imoc_area.json  {"RJTC":2, ...}
      --splice で index.html の /*IMOC_GEN_*/ 区間へ埋め込む
使い方: python3 tools/gen_imoc.py [--splice]
"""
import re, os, sys, json, time, urllib.request

UA = {'User-Agent': 'heli-nav-pwa/1.0 (github.com/yasuokun-pro/heli-nav-pwa)'}
BASE = 'https://www.imoc.co.jp/SmartPhone/d/metar.php?Lang=Jpn&Area=%d'
AREAS = range(0, 11)          # 11以降は韓国・台湾・中国・その他なので対象外


def main():
    m = {}
    for a in AREAS:
        try:
            h = urllib.request.urlopen(
                urllib.request.Request(BASE % a, headers=UA), timeout=30
            ).read().decode('utf-8', 'replace')
        except Exception as e:
            print(f'  Area={a} 取得失敗: {e}', file=sys.stderr); continue
        n = 0
        for icao in re.findall(r'Port=([A-Z0-9\-]+)"', h):
            if re.fullmatch(r'R[JO][A-Z]{2}', icao) and icao not in m:
                m[icao] = a; n += 1
        print(f'  Area={a}: {n} 空港')
        time.sleep(1.2)        # 相手先サーバに配慮
    if len(m) < 80:
        print(f'取得数が少なすぎます({len(m)})。ページ構成が変わった可能性',
              file=sys.stderr); sys.exit(1)

    here = os.path.dirname(os.path.abspath(__file__))
    json.dump(m, open(os.path.join(here, 'imoc_area.json'), 'w'),
              ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    print(f'{len(m)} 空港 → tools/imoc_area.json')

    if '--splice' in sys.argv:
        idx = os.path.join(here, '..', 'index.html')
        h = open(idx).read()
        js = 'const IMOC_AREA=' + json.dumps(m, separators=(',', ':'), sort_keys=True) + ';'
        a, b = '/*IMOC_GEN_START*/', '/*IMOC_GEN_END*/'
        i, j = h.index(a), h.index(b)
        open(idx, 'w').write(h[:i+len(a)] + '\n' + js + '\n' + h[j:])
        print('spliced into index.html')


if __name__ == '__main__': main()
