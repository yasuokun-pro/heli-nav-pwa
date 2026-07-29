#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人口集中地区(DID)レイヤー 生成 (did.json)
==========================================
出典: 国土数値情報「人口集中地区データ」(国土交通省) A16-20 = 2020年国勢調査
      https://nlftp.mlit.go.jp/ksj/  ※利用規約により出典明示が必要

なぜ要るか: 航空法81条・施行規則174条の最低安全高度。
  人又は家屋の密集している地域の上空では、
  **航空機を中心とする水平距離600mの範囲内で最も高い障害物の上端から300m**。
  この「密集地域」の実務上の目安がDID。DIDそのものが法定の区域ではないが、
  国土交通省の通達等でDIDを基準に運用されている。

処理:
  47都道府県のGeoJSONを取得 → 市区町村ごとに分かれているポリゴンを**全部結合**
  (パイロットに要るのは市区町村界ではなく市街地の外周) → 100mで簡略化。
  これで全国7万頂点弱まで落ちる(生データは数百万頂点あり、そのままでは載らない)。

出力: did.json {"year":2020,"src":...,"a":[{"b":[南,北,西,東],"r":[[lat,lng],...]},...]}
  外周リングのみ。b は表示範囲の判定用の外接矩形(全国1000面を毎回描くと重いので、
  アプリ側は画面内のものだけ描く)
使い方:
  python3 tools/gen_did.py           … ダウンロードして生成(初回は数分)
  python3 tools/gen_did.py --cache   … /tmp のダウンロード済みzipから再生成
"""
import json, os, sys, time, zipfile, io, urllib.request

VER = 'A16-20'          # 2020年国勢調査。更新は5年ごと(次は A16-25)
BASE = 'https://nlftp.mlit.go.jp/ksj/gml/data/A16/%s/%s_%02d_GML.zip'
CACHE = '/tmp/did_ksj'
TOL_M = 100             # 簡略化の許容誤差。DID境界自体が統計上の区画なのでこの程度で十分
MIN_AREA_M2 = 40000     # 200m四方未満の飛び地は落とす(表示しても判別できない)


def fetch_pref(n):
    path = f'{CACHE}/{n:02d}.zip'
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.exists(path):
        if '--cache' in sys.argv:
            return None
        url = BASE % (VER, VER, n)
        req = urllib.request.Request(url, headers={'User-Agent': 'heli-nav-pwa/1.0'})
        with urllib.request.urlopen(req, timeout=180) as r:
            open(path, 'wb').write(r.read())
        time.sleep(1.0)                      # 相手先サーバに配慮
    with zipfile.ZipFile(path) as z:
        name = next((m for m in z.namelist() if m.endswith('.geojson')), None)
        if not name: return None
        return json.loads(z.read(name))


def main():
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union
    except ImportError:
        print('shapely が必要です: python3 -m pip install --user shapely', file=sys.stderr)
        sys.exit(1)

    geoms = []
    for n in range(1, 48):
        d = fetch_pref(n)
        if not d:
            print(f'  {n:02d}: skip'); continue
        # buffer(0) で自己交差を直しておかないと unary_union が落ちることがある
        geoms += [shape(f['geometry']).buffer(0) for f in d['features']]
        print(f'  {n:02d}: 累計 {len(geoms)} ポリゴン', flush=True)

    print('結合中…', flush=True)
    u = unary_union(geoms)
    parts = list(u.geoms) if hasattr(u, 'geoms') else [u]
    print(f'  {len(parts)} 面')

    tol = TOL_M / 111320.0
    min_deg2 = MIN_AREA_M2 / (111320.0 ** 2)
    rings = []
    for g in parts:
        if g.area < min_deg2: continue
        s = g.simplify(tol)
        if s.is_empty: continue
        for gg in (s.geoms if hasattr(s, 'geoms') else [s]):
            # 緯度経度4桁(約11m)で十分。ファイルサイズがほぼ半分になる
            r = [[round(y, 4), round(x, 4)] for x, y in gg.exterior.coords]
            la = [p[0] for p in r]; lo = [p[1] for p in r]
            rings.append({'b': [min(la), max(la), min(lo), max(lo)], 'r': r})

    rings.sort(key=lambda x: -len(x['r']))
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'did.json')
    json.dump({'year': 2020, 'tol_m': TOL_M,
               'src': '国土数値情報(人口集中地区データ)国土交通省', 'a': rings},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(rings)} 面 / 頂点 {sum(len(r["r"]) for r in rings)} '
          f'→ did.json ({os.path.getsize(dst)/1024:.0f}KB)')


if __name__ == '__main__': main()
