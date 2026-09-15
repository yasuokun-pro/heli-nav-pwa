#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
送電線レイヤー生成 (pwln.json)
================================
OpenStreetMap の `power=line`(送電線)を Overpass API から取得して軽量JSONにまとめる。

なぜ要るか:
  AIS の障害物データ(obst.json)は**点**しか無い。鉄塔は載っていても
  **鉄塔と鉄塔の間に張られている線そのものは入っていない**。実際にぶつかるのは線の方で、
  とくに**川を横断する送電線**は河川敷に降りるときの最大の脅威。そこを埋める。

⚠ `power=minor_line`(配電線)は日本ではOSMにほとんど入っていない(千葉中央部で0本)。
  このレイヤーは**送電線だけ**。線が描かれていない=安全、では絶対にない。
⚠ 出典表記が要る(ODbL)。地図の attribution に OpenStreetMap contributors を出すこと。

使い方:
  python3 tools/gen_pwln.py            # 全国(キャッシュがあれば使う)
  python3 tools/gen_pwln.py --stat     # 取得済みキャッシュの統計だけ

⚠ Overpass は混んでいると 504 を即返す。ミラーを回して、それでもだめなら
  **区画を4分割して**取り直す(密な区画ほど自動的に細かくなる)。
⚠ 公開インスタンスへの負荷を避けるため、逐次実行+待ちを入れている。並列化しないこと。
"""
import json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = '/tmp/pwln_cache'
UA = 'heli-nav-pwa/1.0 (personal flight planning; mayfair.sss3250@gmail.com)'
# ⚠ 公開インスタンスはよく混む。504(スロット無し)や接続断が普通に起きるので必ず複数持つ
MIRRORS = ['https://maps.mail.ru/osm/tools/overpass/api/interpreter',
           'https://overpass-api.de/api/interpreter',
           'https://overpass.kumi.systems/api/interpreter',
           'https://overpass.private.coffee/api/interpreter']
# 日本の陸域をだいたい覆う箱(南西端, 北東端)。海しかない区画は空で速く返る
# ⚠ 本州・九州・北海道を先に取る(実用上いちばん要る)。南西諸島は最後
BOXES = [(34.0, 134.5, 38.0, 141.2),    # 中国東部〜関東
         (32.5, 132.0, 35.5, 137.0),    # 四国・紀伊
         (30.8, 129.2, 34.9, 135.2),    # 九州
         (37.5, 138.0, 41.8, 142.2),    # 東北
         (41.0, 139.2, 45.8, 146.0),    # 北海道
         (24.0, 122.8, 28.0, 131.5)]    # 南西諸島
STEP = 2.0          # 最初の区画(度)。混んでいる時は取れた方が速いので大きめにして、だめなら4分割
MAXDEPTH = 3        # 4分割の上限(1.0 → 0.125度)


def fetch(q, tries=6):
    """Overpass に投げる。504/タイムアウトはミラーを替えて待って再試行"""
    for i in range(tries):
        url = MIRRORS[i % len(MIRRORS)]
        try:
            req = urllib.request.Request(url + '?' + urllib.parse.urlencode({'data': q}),
                                         headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            time.sleep(min(8 * (i + 1), 40))
    return None


def cell(s, w, n, e, depth=0):
    """1区画ぶんの way を返す。取れなければ4分割して取り直す"""
    key = f'{s:.3f}_{w:.3f}_{n:.3f}_{e:.3f}.json'
    p = os.path.join(CACHE, key)
    if os.path.exists(p):
        return json.load(open(p))
    q = (f'[out:json][timeout:280];way["power"="line"]({s},{w},{n},{e});out geom;')
    d = fetch(q, tries=3 if depth < MAXDEPTH else 6)
    if d is None:
        if depth >= MAXDEPTH:
            print(f'   !! あきらめ {key}', flush=True)
            return []
        print(f'   .. 4分割 {key}', flush=True)
        my, mx = (s + n) / 2, (w + e) / 2
        out = []
        for a, b, c, dd in ((s, w, my, mx), (s, mx, my, e), (my, w, n, mx), (my, mx, n, e)):
            out += cell(a, b, c, dd, depth + 1)
        json.dump(out, open(p, 'w')); return out
    out = [{'id': x['id'], 'g': [[round(g['lat'], 5), round(g['lon'], 5)] for g in x.get('geometry', [])],
            'v': x.get('tags', {}).get('voltage', '')} for x in d['elements'] if x.get('geometry')]
    json.dump(out, open(p, 'w'))
    time.sleep(2)
    return out


def kv(v):
    """voltage タグ(「275000;154000」等)の最大値をkVで返す"""
    best = 0
    for t in str(v).replace(',', ';').split(';'):
        t = ''.join(ch for ch in t if ch.isdigit())
        if t: best = max(best, int(t) // 1000)
    return best


def main():
    os.makedirs(CACHE, exist_ok=True)
    ways = {}
    boxes = BOXES
    if '--kanto' in sys.argv: boxes = [(34.8, 138.4, 37.2, 141.0)]   # 動作確認用
    if '--stat' not in sys.argv:
        for (s0, w0, n0, e0) in boxes:
            la = s0
            while la < n0:
                lo = w0
                while lo < e0:
                    for x in cell(la, lo, min(la + STEP, n0), min(lo + STEP, e0)):
                        ways[x['id']] = x
                    print(f'  {la:.1f},{lo:.1f} 累計 {len(ways)} 本', flush=True)
                    lo += STEP
                la += STEP
    else:
        for f in os.listdir(CACHE):
            for x in json.load(open(os.path.join(CACHE, f))): ways[x['id']] = x

    lines, nodes = [], 0
    for x in ways.values():
        g = x['g']
        if len(g) < 2: continue
        nodes += len(g)
        # 差分整数(1e5倍)にして小さくする: [lat0,lng0,dlat,dlng,...]
        a = [round(g[0][0] * 1e5), round(g[0][1] * 1e5)]
        for i in range(1, len(g)):
            a.append(round(g[i][0] * 1e5) - round(g[i - 1][0] * 1e5))
            a.append(round(g[i][1] * 1e5) - round(g[i - 1][1] * 1e5))
        lines.append([kv(x['v'])] + a)
    out = {'updated': time.strftime('%Y-%m-%d'), 'scale': 100000,
           'src': 'OpenStreetMap contributors (ODbL) power=line',
           'l': lines}
    dst = os.path.join(HERE, '..', 'pwln.json')
    json.dump(out, open(dst, 'w'), separators=(',', ':'))
    print(f'{len(lines)} 本 / 節点 {nodes} → pwln.json ({os.path.getsize(dst)/1024/1024:.1f}MB)')


if __name__ == '__main__':
    main()
