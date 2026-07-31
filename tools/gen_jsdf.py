#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自衛隊・在日米軍施設レイヤー 生成 (jsdf.json)
=============================================
出典: OpenStreetMap (ODbL) + ウィキペディア日本語版 (CC BY-SA)
      + 陸上自衛隊公式サイトの駐屯地一覧(tools/gsdf_stations.json)。
AIPには飛行場しか載らないため、駐屯地・分屯地・演習場といった
「飛行場ではない施設」はこの3つから拾う。

  OSM      … 敷地の外形ポリゴンが取れる。ただし2割ほど欠落がある
  ウィキペ … 座標(点)だけだが一覧としては網羅性が高い。OSMに無い分の穴埋めに使う
  陸自公式 … **陸自の駐屯地・分屯地163件の正式名称と番地までの住所**。
             OSM/ウィキペの取りこぼしを機械的に検出する突合表として使う
             (座標は無いのでジオコーダにかける)

  ⚠ OSMは有志が作るデータなので網羅性・位置精度は保証されない。
    「そこに施設がある」目安として使い、進入可否等の判断には使わないこと。
    アプリ側にもその旨を表示している(消さないこと)。

出力: jsdf.json  {"src":...,"f":[{n,s,t,lat,lng,p?,w?},...]}
  n=名称 s=所属(陸/海/空/米/防) t=種別(飛/駐/演/基/他)
  p=外周座標(簡略化済・OSM由来のみ) w=1ならウィキペディア由来の点データ

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
                  r'補給処|補給廠|射場|試験場|防衛省|Camp |Air (Base|Station)|Naval')

# OSMの名称が通称と違うものを直す。市ヶ谷は「防衛省市ヶ谷地区」で登録されていて
# 「駐屯地」も「基地」も付かないため、名前での絞り込みから漏れていた
NAME_FIX = {'防衛省市ヶ谷地区': '市ヶ谷駐屯地', '防衛省 目黒地区': '目黒駐屯地'}

# ウィキペディアのカテゴリには**廃止された施設**も入っている
# (檜町駐屯地は2000年に市ヶ谷へ移転して廃止、芝浦分屯地も同年廃止で現在は公園)。
# 判定は**冒頭2文だけ**を見て、施設の存在が過去形で書かれているものを落とす。
#   ⚠「返還」「移転し」を含めると現役の基地まで落ちる
#     (恩納分屯基地=沖縄返還協定で移管、千歳基地/熊谷基地も沿革に出てくる)
WP_GONE = re.compile(r'所在していた|にあった|駐屯していた|配置されていた|'
                     r'(廃止|閉鎖)された')

# OSMに無い施設を座標直指定で足す。座標は国土地理院のジオコーディング
# (https://msearch.gsi.go.jp/address-search/AddressSearch) で住所から求めたもの
EXTRA_PT = [
    ('用賀駐屯地', '陸', '駐', 35.63307, 139.63788),   # 世田谷区上用賀1-20-1
]

# 軍事タグが付かないので上の抽出には入らないが、載せておきたい施設。
# OSMのID直指定でAPIから取る(所属は '官' = 官邸・内閣府)
EXTRA = [
    ('way/145495603', '内閣府8号館(中央合同庁舎第8号館)', '官', '他'),
    ('relation/7826113', '首相官邸', '官', '他'),
]
KEEP_TAG = {'airfield', 'naval_base', 'range', 'base'}
# 除外(戦跡・記念物、警察/海保など自衛隊以外、返還済み)
DROP = re.compile(r'掩体|防空壕|跡$|跡地|返還|旧|historical|記念|資料館|史跡|公園|'
                  r'免許センター|協力本部|援護|警察|機動隊|海上保安|消防|'
                  r'Residental|Residential|Classroom|福岡第一')  # 基地内の細かい区画は除く
# bboxが日本国外にはみ出すので国外の施設を落とす(千島=ロシア、舟山=中国 等)
FOREIGN = re.compile(r'[\u0400-\u04FF]')          # キリル文字(千島のロシア施設)
# 除外は「はみ出す隣国」だけを箱で指定する。緯度経度の大小で切ると
# 先島諸島(宮古島24.8N/125.3E 等)まで巻き込むので必ず箱で書くこと
EXCLUDE = [(28.0, 118.0, 33.5, 123.5),   # 中国本土・舟山
           (44.5, 145.5, 47.0, 155.0)]   # 択捉以北(ロシア)
def in_japan(lat, lng):
    return not any(a <= lat <= c and b <= lng <= d for a, b, c, d in EXCLUDE)


# 名前から所属が読み取れないもの(共用飛行場・沖縄の米軍施設など)を手当て
SVC_FIX = {'厚木海軍飛行場': '海', '普天間飛行場': '米', 'キャンプ桑江': '米',
           '北部訓練場': '米', '小松飛行場': '空', '美保飛行場': '空',
           '徳島飛行場': '海', '札幌飛行場': '陸',
           '市ヶ谷駐屯地': '防',     # 防衛省本省の所在地なので所属は防衛省とする
           '目黒駐屯地': '陸'}       # 防衛研究所等が入るが陸自の駐屯地


def service(name, tags):
    """所属を1文字に。米軍を先に判定する(「米軍◯◯基地」を空自と誤らせない)"""
    for k, v in SVC_FIX.items():
        if k in name: return v
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
    if re.search(r'演習場|射撃場|訓練場', name): return '陸'  # 演習場はほぼ陸自
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
    n = NAME_FIX.get(name.strip(), name).split(';')[0].strip()
    n = re.sub(r'^(陸上|海上|航空)自衛隊\s*', '', n)
    n = re.sub(r'\s*[（(]?JGSDF|JASDF|JMSDF[）)]?\s*', '', n)
    # ウィキペディアの曖昧さ回避「佐世保基地 (アメリカ海軍)」→「佐世保基地」
    n = re.sub(r'\s*[（(][^）)]*[）)]?\s*$', '', n)
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


WP_CATS = ['自衛隊基地', '在日米軍基地', '海上自衛隊の陸上施設',
           '陸上自衛隊駐屯地', '航空自衛隊の基地']
WP_KEEP = re.compile(r'駐屯地|分屯地|分屯基地|基地|演習場|飛行場|航空隊|訓練場|射場|試験場')


def wp_api(params):
    """ja.wikipedia API。連続で叩くと429が返るので必ず間を空けて呼ぶこと"""
    import urllib.parse
    for a in range(5):
        try:
            u = 'https://ja.wikipedia.org/w/api.php?format=json&' + urllib.parse.urlencode(params)
            req = urllib.request.Request(u, headers={
                'User-Agent': 'heli-nav-pwa/1.0 (github.com/yasuokun-pro/heli-nav-pwa)'})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            time.sleep(2 + a * 2)
    return {}


def fetch_extra():
    """OSM APIからID指定で取る。Overpassは混むと落ちるうえ、
       件数が数件なら公式APIのほうが確実"""
    path = '/tmp/jsdf_extra.json'
    if '--cache' in sys.argv and os.path.exists(path):
        return json.load(open(path))
    out = []
    for oid, name, svc, kind_ in EXTRA:
        req = urllib.request.Request(
            f'https://api.openstreetmap.org/api/0.6/{oid}/full.json',
            headers={'User-Agent': 'heli-nav-pwa/1.0 (github.com/yasuokun-pro/heli-nav-pwa)'})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())['elements']
        nodes = {e['id']: [e['lat'], e['lon']] for e in d if e['type'] == 'node'}
        ways = {e['id']: e for e in d if e['type'] == 'way'}
        if oid.startswith('way/'):
            ring = [nodes[n] for n in ways[int(oid.split('/')[1])]['nodes'] if n in nodes]
        else:   # relationは外周のwayを繋いで使う
            rel = [e for e in d if e['type'] == 'relation'][0]
            ring = []
            for m in rel['members']:
                if m['type'] == 'way' and m.get('role') in ('outer', '') and m['ref'] in ways:
                    ring += [nodes[n] for n in ways[m['ref']]['nodes'] if n in nodes]
        if len(ring) < 3: continue
        out.append({'n': name, 's': svc, 't': kind_,
                    'lat': round(sum(p[0] for p in ring) / len(ring), 5),
                    'lng': round(sum(p[1] for p in ring) / len(ring), 5),
                    'p': [[round(a, 5), round(b, 5)] for a, b in ring]})
        time.sleep(1.0)
    json.dump(out, open(path, 'w'), ensure_ascii=False)
    return out


def gsi_geocode(addr):
    """国土地理院のジオコーダで住所→座標。ウィキペディアに座標が無い記事用
       (大宮駐屯地・用賀駐屯地など。記事冒頭に必ず住所が書いてある)"""
    import urllib.parse
    try:
        u = ('https://msearch.gsi.go.jp/address-search/AddressSearch?q='
             + urllib.parse.quote(addr))
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(u, headers={'User-Agent': 'heli-nav-pwa/1.0'}),
            timeout=30).read())
        if d:
            c = d[0]['geometry']['coordinates']
            return [round(c[1], 5), round(c[0], 5)]
    except Exception:
        pass
    return None


ADDR = re.compile(r'((?:北海道|東京都|(?:京都|大阪)府|\S{2,3}県)[^、。]{3,40}?)(?:に所在|に位置|にある)')

# --- 陸自公式サイトの駐屯地一覧との突合 -------------------------------------
# https://www.mod.go.jp/gsdf/station/{na,nea,ea,ma,wa}/ の163件を
# tools/gsdf_stations.json に落としてある(名称+郵便番号+番地までの住所)。
#   ⚠ 同サイトは Cloudflare のbot判定が入るので curl / urllib では 403 になる。
#     更新するときはブラウザで開いて document.body.innerText から拾うこと。
# 突合は2段。
#  1) 同名のものが既にあれば同一施設とみなす(距離は見ない)。礼文・別海・日高の
#     ように敷地が広く住所が「字◯◯」だけの所は、ジオコーダの点が外形の中心から
#     10km近く離れるので、距離で切ると二重登録になる
#  2) 同名が無ければ「名前の芯が一致」かつ「6km以内」で探す。OSMでは
#     霞目駐屯地→霞目飛行場、相馬原駐屯地→相馬原演習場、座間駐屯地→米軍キャンプ座間
#     のように別名で入っている。距離を外すと静内駐屯地が10km離れた
#     静内対空射撃場に誤って吸収されるので距離判定は必須
# さらに、同名でも**外形の無い点データ**が公式住所から10km以上ずれている場合は
# 公式住所側を採用して直す(玖珠駐屯地と湯布院駐屯地はウィキペディア由来の座標が
# 入れ替わっていた)。
GSDF_R_KM = 6.0
GSDF_FIX_KM = 10.0
# 「同じ場所の別名」とみなす名前(演習場・射撃場は含めない。別の場所なので)
GSDF_SAME = re.compile(r'飛行場|基地|駐屯地|分屯地|地区|キャンプ|Camp ')


def gsdf_roster():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, 'gsdf_stations.json')
    if not os.path.exists(p): return []
    return json.load(open(p))['f']


def gsdf_check(out):
    """公式一覧に載っていて jsdf.json に無い駐屯地を点データで足す"""
    import math
    roster = gsdf_roster()
    if not roster: return 0
    cache_p = '/tmp/jsdf_gsdf_geo.json'
    geo = json.load(open(cache_p)) if os.path.exists(cache_p) else {}
    def km(a, b):
        return math.hypot((a[0]-b[0])*111, (a[1]-b[1])*91)

    add = fix = 0
    for r in roster:
        n, ad = r['n'], r['ad']
        if n not in geo:
            geo[n] = gsi_geocode(ad)
            time.sleep(1.0)
            json.dump(geo, open(cache_p, 'w'), ensure_ascii=False)
        c = geo[n]
        if not c:
            print(f'  住所を座標に出来ない: {n} ({ad})'); continue
        same = next((m for m in out if m['n'] == n), None)
        if same:
            d = km((same['lat'], same['lng']), c)
            if not same.get('p') and d > GSDF_FIX_KM:
                print(f'  座標を公式住所で修正: {n} {d:.0f}km ずれ → {ad}')
                same['lat'], same['lng'] = c
                same['g'] = 1; same.pop('w', None); fix += 1
            continue
        base = re.sub(r'(駐屯地|分屯地)$', '', n)
        near = [m for m in out
                if base in m['n'] and km((m['lat'], m['lng']), c) < GSDF_R_KM]
        # 演習場・射撃場は駐屯地とは別の場所。「習志野演習場」があっても
        # 習志野駐屯地(2km南)は別に立てる。基地・飛行場側の名前で入っている
        # ものだけを同一施設とみなす
        if any(GSDF_SAME.search(m['n']) or km((m['lat'], m['lng']), c) < 1.5
               for m in near):
            continue
        out.append({'n': n, 's': '陸', 't': '駐', 'lat': c[0], 'lng': c[1], 'g': 1})
        print(f'  公式一覧から補完: {n} ({ad})')
        add += 1
    if fix: print(f'  {fix} 件の座標を修正')
    return add


def fetch_wp():
    """カテゴリを1階層だけ辿って記事名を集め、まとめて座標を引く"""
    path = '/tmp/jsdf_wp.json'
    if '--cache' in sys.argv and os.path.exists(path):
        return json.load(open(path))

    def members(cat, depth=0):
        out = []
        d = wp_api({'action': 'query', 'list': 'categorymembers',
                    'cmtitle': 'Category:' + cat, 'cmlimit': 500})
        time.sleep(1.0)
        for m in d.get('query', {}).get('categorymembers', []):
            if m['ns'] == 14 and depth < 1:      # サブカテゴリは1段だけ(都道府県別は巨大)
                out += members(m['title'].split(':', 1)[1], depth + 1)
            elif m['ns'] == 0:
                out.append(m['title'])
        return out

    titles = sorted({t for c in WP_CATS for t in members(c) if WP_KEEP.search(t)})
    coords = {}
    for i in range(0, len(titles), 20):
        d = wp_api({'action': 'query', 'prop': 'coordinates|extracts',
                    'exintro': 1, 'explaintext': 1, 'exlimit': 'max',
                    'titles': '|'.join(titles[i:i+20]), 'colimit': 'max'})
        for pg in d.get('query', {}).get('pages', {}).values():
            c = pg.get('coordinates')
            if not c: continue
            head = '。'.join((pg.get('extract') or '').split('。')[:2])
            if WP_GONE.search(head):
                print(f'  廃止済みとして除外: {pg["title"]}')
                continue
            coords[pg['title']] = [c[0]['lat'], c[0]['lon']]
        time.sleep(2.0)         # 連打すると429になる
    json.dump(coords, open(path, 'w'), ensure_ascii=False)
    return coords


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
        raw = NAME_FIX.get(raw.strip(), raw)
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

    # OSMに無い施設をウィキペディアの座標で補う(点データ・外形なし)
    print('ウィキペディアで欠落分を補完中…')
    add = 0
    for title, v in fetch_wp().items():
        lat, lng = v[0], v[1]
        geo = len(v) > 2                # 住所をジオコーダにかけたもの
        # カテゴリには学校・宿舎・弾薬庫等も入るので施設名で絞る(キャッシュ経由でも効かせる)
        if not WP_KEEP.search(title) or DROP.search(title): continue
        n = clean(title)
        base = re.sub(r'(駐屯地|分屯地|分屯基地|基地|飛行場|航空基地|演習場)$', '', n)
        if any(abs(m['lat']-lat) < 0.03 and abs(m['lng']-lng) < 0.04 and
               (base and (base in m['n'] or m['n'].replace(' ', '') in n)) for m in out):
            continue
        out.append({'n': n, 's': service(title, {}), 't': kind(title, {}),
                    'lat': round(lat, 5), 'lng': round(lng, 5),
                    **({'g': 1} if geo else {'w': 1})})
        add += 1
    print(f'  {add} 件を補完')
    for x in fetch_extra():
        if not any(r['n'] == x['n'] for r in out): out.append(x)
    for n, sv, ki, la, lo in EXTRA_PT:
        if not any(r['n'] == n for r in out):
            out.append({'n': n, 's': sv, 't': ki, 'lat': la, 'lng': lo, 'g': 1})

    print('陸自公式の駐屯地一覧と突合中…')
    print(f'  {gsdf_check(out)} 件を補完')

    out.sort(key=lambda r: (r['s'], r['n']))
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'jsdf.json')
    json.dump({'src': 'OpenStreetMap (ODbL) / ウィキペディア日本語版 (CC BY-SA)'
                      ' / 陸上自衛隊公式サイト 駐屯地一覧', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    import collections
    print(f'{len(out)} 件 → jsdf.json ({os.path.getsize(dst)/1024:.0f}KB)')
    print(' 所属:', dict(collections.Counter(r['s'] for r in out)))
    print(' 種別:', dict(collections.Counter(r['t'] for r in out)))
    print(' 外形あり:', sum(1 for r in out if r.get('p')), '/ 点のみ:', sum(1 for r in out if not r.get('p')))


if __name__ == '__main__': main()
