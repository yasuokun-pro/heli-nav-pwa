#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自衛隊・在日米軍施設レイヤー 生成 (jsdf.json)
=============================================
出典: OpenStreetMap (ODbL)。AIPには飛行場しか載らないため、
駐屯地・分屯地・演習場といった「飛行場ではない施設」はOSMから拾う。

  ⚠ OSMは有志が作るデータなので網羅性・位置精度は保証されない。
    「そこに施設がある」目安として使い、進入可否等の判断には使わないこと。
    アプリ側にもその旨を表示している(消さないこと)。

出力: jsdf.json  {"src":"OpenStreetMap (ODbL)","f":[{n,s,t,lat,lng,p?},...]}
  n=名称 s=所属(陸/海/空/米/防) t=種別(飛/駐/演/基/他) p=外周座標(簡略化済・任意)

使い方:
  python3 tools/gen_jsdf.py            … Overpassから取得して生成
  python3 tools/gen_jsdf.py --cache    … /tmp の取得済みJSONから再生成のみ
"""
import json, re, os, sys, time, urllib.request

OVERPASS = 'https://overpass-api.de/api/interpreter'
# 日本全域を4分割(1クエリで全国を投げるとOverpassがタイムアウトする)
BBOXES = ['24,122,31,132', '31,128,35,137', '34,135,38,142', '37,138,46,154']
CACHE = '/tmp/jsdf_osm_%d.json'

Q_LIST = """[out:json][timeout:150];
(
  way["landuse"="military"](%s);
  relation["landuse"="military"](%s);
  way["military"](%s);
  relation["military"](%s);
  nwr["aeroway"~"^(heliport|aerodrome)$"]["military"](%s);
);
out tags center;"""

# 拾う施設(名称 or militaryタグで判定)。掩体壕・防空壕・検問所等の細かい物件は除く
KEEP = re.compile(r'駐屯地|分屯地|分屯基地|基地|飛行場|演習場|航空隊|地方総監部|'
                  r'補給処|補給廠|射場|試験場|Camp |Air (Base|Station)|Naval')
KEEP_TAG = {'airfield', 'naval_base', 'range', 'base'}
# 除外(戦跡・記念物、警察/海保など自衛隊以外、返還済み)
DROP = re.compile(r'掩体|防空壕|跡$|跡地|返還|旧|historical|記念|資料館|史跡|公園|'
                  r'免許センター|協力本部|援護|警察|機動隊|海上保安|消防')
# bboxが日本国外にはみ出すので国外の施設を落とす(千島=ロシア、舟山=中国 等)
FOREIGN = re.compile(r'[\u0400-\u04FF]')          # キリル文字(千島のロシア施設)
# 除外は「はみ出す隣国」だけを箱で指定する。緯度経度の大小で切ると
# 先島諸島(宮古島24.8N/125.3E 等)まで巻き込むので必ず箱で書くこと
EXCLUDE = [(28.0, 118.0, 33.5, 123.5),   # 中国本土・舟山
           (44.5, 145.5, 47.0, 155.0)]   # 択捉以北(ロシア)
def in_japan(lat, lng):
    return not any(a <= lat <= c and b <= lng <= d for a, b, c, d in EXCLUDE)


def service(name, tags):
    """所属を1文字に。米軍を先に判定する(「米軍◯◯基地」を空自と誤らせない)"""
    s = name + ' ' + (tags.get('operator', '') or '') + ' ' + (tags.get('operator:en', '') or '')
    if re.search(r'米軍|在日米|United States|U\.S\.|US (Army|Navy|Air|Marine)|USMC|USAF', s): return '米'
    if re.search(r'航空自衛隊|空自|JASDF|Air Self', s): return '空'
    if re.search(r'海上自衛隊|海自|JMSDF|Maritime Self', s): return '海'
    if re.search(r'陸上自衛隊|陸自|JGSDF|Ground Self', s): return '陸'
    if re.search(r'防衛省|防衛大学校|防衛装備庁', s): return '防'
    # 「◯◯駐屯地」は陸自、「◯◯基地/分屯基地」は空自が大半
    if '駐屯地' in name or '分屯地' in name: return '陸'
    if '航空基地' in name: return '海'
    if '基地' in name: return '空'
    return '他'


def kind(name, tags):
    m = tags.get('military', '')
    if '飛行場' in name or m == 'airfield' or tags.get('aeroway'): return '飛'
    if '演習場' in name or m == 'range': return '演'
    if '駐屯地' in name or '分屯地' in name: return '駐'
    if '基地' in name or m in ('base', 'naval_base'): return '基'
    return '他'


def clean(name):
    """「陸上自衛隊 立川駐屯地」→「立川駐屯地」。所属は s に持たせるので前置きを外す"""
    n = name.split(';')[0].strip()
    n = re.sub(r'^(陸上|海上|航空)自衛隊\s*', '', n)
    n = re.sub(r'\s*[（(]?JGSDF|JASDF|JMSDF[）)]?\s*', '', n)
    n = re.sub(r'\s+', ' ', n).strip(' （）()')
    return n


def simplify(pts, tol_m=60):
    """Douglas-Peucker。駐屯地の外形は目安表示なので60m程度まで間引いてよい"""
    try:
        from shapely.geometry import LineString
    except ImportError:
        return pts
    if len(pts) < 4: return pts
    # 緯度経度を度のまま扱うと東西が縮むので、経度を cos(lat) 倍して等方に近づける
    import math
    k = math.cos(math.radians(pts[0][0]))
    tol = tol_m / 111320.0
    ls = LineString([(p[1] * k, p[0]) for p in pts]).simplify(tol)
    return [[round(y, 5), round(x / k, 5)] for x, y in ls.coords]


def fetch():
    els = {}
    for i, bb in enumerate(BBOXES):
        path = CACHE % i
        if '--cache' in sys.argv and os.path.exists(path):
            data = json.load(open(path))
        else:
            q = Q_LIST % (bb, bb, bb, bb, bb)
            req = urllib.request.Request(OVERPASS, data=q.encode(),
                                         headers={'User-Agent': 'heli-nav-pwa/1.0'})
            data = json.loads(urllib.request.urlopen(req, timeout=200).read())
            json.dump(data, open(path, 'w'))
            time.sleep(8)  # Overpassの負荷制限に配慮
        for e in data['elements']: els[(e['type'], e['id'])] = e
        print(f'  bbox{i+1}: 累計 {len(els)}')
    return els


def fetch_geom(ids):
    """外形が要るものだけ2回目のクエリで取り直す(全件geomは重い)"""
    parts = []
    for ty, pfx in (('way', 'way'), ('relation', 'rel'), ('node', 'node')):
        v = ids.get(ty, [])
        for i in range(0, len(v), 200):
            parts.append(' %s(id:%s);' % (pfx, ','.join(map(str, v[i:i+200]))))
    q = '[out:json][timeout:180];(\n' + '\n'.join(parts) + '\n);\nout geom;'
    path = '/tmp/jsdf_osm_geom.json'
    if '--cache' in sys.argv and os.path.exists(path):
        return json.load(open(path))
    req = urllib.request.Request(OVERPASS, data=q.encode(),
                                 headers={'User-Agent': 'heli-nav-pwa/1.0'})
    d = json.loads(urllib.request.urlopen(req, timeout=220).read())
    json.dump(d, open(path, 'w'))
    return d


def main():
    print('Overpassから取得中(4分割)…')
    els = fetch()
    ids, meta = {'way': [], 'relation': [], 'node': []}, {}
    for (ty, i), e in els.items():
        t = e.get('tags', {})
        nm = t.get('name') or t.get('name:ja') or ''
        if not nm or DROP.search(nm) or FOREIGN.search(nm): continue
        ctr = e.get('center') or e
        if not in_japan(ctr.get('lat', 0), ctr.get('lon', 0)): continue
        if not (KEEP.search(nm) or t.get('military') in KEEP_TAG): continue
        ids[ty].append(i); meta[(ty, i)] = t
    print(f'対象 {len(meta)} 件 → 外形を取得中…')
    g = fetch_geom(ids)

    out, seen = [], {}
    for e in g['elements']:
        t = meta.get((e['type'], e['id']))
        if not t: continue
        raw = t.get('name') or t.get('name:ja') or ''
        n = clean(raw)
        pts = None
        if e['type'] == 'node':
            lat, lng = e['lat'], e['lon']
        else:
            gm = e.get('geometry') or (e.get('members') or [{}])[0].get('geometry')
            if not gm: continue
            pts = [[p['lat'], p['lon']] for p in gm]
            lat = sum(p[0] for p in pts) / len(pts)
            lng = sum(p[1] for p in pts) / len(pts)
        # 同名が近接して複数ある場合(基地を分割して描いてある等)は広い方を残す
        key = (n, round(lat, 1), round(lng, 1))
        rec = {'n': n, 's': service(raw, t), 't': kind(raw, t),
               'lat': round(lat, 5), 'lng': round(lng, 5)}
        if pts and len(pts) > 3: rec['p'] = simplify(pts)
        prev = seen.get(key)
        if prev and len(prev.get('p') or []) >= len(rec.get('p') or []): continue
        if prev: out.remove(prev)
        seen[key] = rec; out.append(rec)

    # OSMでは同じ場所が「立川駐屯地」と「立川飛行場」のように二重登録されている。
    # 2km以内に別名の施設があれば、外形の大きい方(=本体)を残す
    import math
    out.sort(key=lambda r: -len(r.get('p') or []))
    merged = []
    for r in out:
        base = re.sub(r'(駐屯地|分屯地|分屯基地|基地|飛行場|航空基地)$', '', r['n'])
        dup = next((m for m in merged
                    if base and base in m['n']
                    and abs(m['lat']-r['lat']) < 0.02 and abs(m['lng']-r['lng']) < 0.025), None)
        if dup:
            if dup['t'] == '他' and r['t'] != '他': dup['t'] = r['t']
            if dup['s'] == '他' and r['s'] != '他': dup['s'] = r['s']
            continue
        merged.append(r)
    out = merged
    out.sort(key=lambda r: (r['s'], r['n']))
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'jsdf.json')
    json.dump({'src': 'OpenStreetMap (ODbL)', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    import collections
    print(f'{len(out)} 件 → jsdf.json ({os.path.getsize(dst)/1024:.0f}KB)')
    print(' 所属:', dict(collections.Counter(r['s'] for r in out)))
    print(' 種別:', dict(collections.Counter(r['t'] for r in out)))


if __name__ == '__main__': main()
