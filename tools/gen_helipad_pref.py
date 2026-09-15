#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
都県の地域防災計画で場着場を最新化 (helipad_pref.json)
=======================================================
`helipad.json`(国土数値情報 N11-13・平成25年)は**2013年から更新されていない**ので、
都県が公開している**現行の地域防災計画の一覧**で上書きする。

やり方(座標の精度を落とさないため、単純な差し替えにはしない):
  1. 都県の最新リストを解析(名称・所在地・面積・現況・備考)
  2. **N11 の同じ都県の点と名称/住所で突合** → 一致したら**N11の座標を流用**して属性だけ更新
     (住所のジオコーディングより、施設の実位置である N11 の座標の方が正確)
  3. 突合できなかった新規分だけ**国土地理院のジオコーダ**で座標化
  4. 県のリストから消えた点は落とす(古い情報を残さない)

使い方:
  python3 tools/gen_helipad_pref.py 13        # 東京都だけ
  python3 tools/gen_helipad_pref.py           # 定義済みの全都県
  python3 tools/gen_helipad_pref.py 13 --dry  # 突合結果だけ見る(ジオコーダを叩かない)

⚠ 資料の書式は都県ごとにばらばら。1都県ずつ PARSERS に足していく。
⚠ ジオコーダは 1秒に1回まで。番地まで無い住所は市区町村の中心に落ちるので、
  **突合できた点はN11の座標を優先**する(この方針を崩さないこと)
"""
import json, os, re, sys, time, unicodedata, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'heli-nav-pwa/1.0'}
CACHE = '/tmp/helipad_pref'
GSI = 'https://msearch.gsi.go.jp/address-search/AddressSearch?q='
# 住所らしい語: 区市町村のあとに数字・丁目・字などが続くもの(施設名の「◯◯区立」を弾く)
ADDR = re.compile(r'[一-龥ぁ-んァ-ヶー]{1,8}[区市町村](?=[^\s]*(?:[0-9０-９]|丁目|番|字|先|地内))')


def cw(c): return 2 if unicodedata.east_asian_width(c) in 'WFA' else 1
def dpos(s, i): return sum(cw(c) for c in s[:i])
def cidx(s, d):
    t = 0
    for i, c in enumerate(s):
        if t >= d: return i
        t += cw(c)
    return len(s)


def get(url, path=None, binary=True):
    if path:
        os.makedirs(CACHE, exist_ok=True)
        p = os.path.join(CACHE, path)
        if os.path.exists(p): return open(p, 'rb').read() if binary else open(p, encoding='utf-8').read()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r: b = r.read()
    if path: open(p, 'wb').write(b)
    return b if binary else b.decode('utf-8', 'replace')


def pdftext(url, name):
    import subprocess
    get(url, name + '.pdf')
    p = os.path.join(CACHE, name + '.pdf')
    return subprocess.run(['pdftotext', '-layout', p, '-'], capture_output=True, text=True).stdout


# ── 表の切り出し(共通) ───────────────────────────────────────────────
def rows_by_columns(lines, numbered=r'^\s{0,6}(\d{1,4})(?:\s|$)'):
    """番号付きの行を1件として、**住所欄の桁**を基準に 名称/住所/以降 に割る。
    ⚠ 名称が長いと番号行の上下に折り返す。名称の桁の範囲に収まる行だけを継ぐ"""
    num = re.compile(numbered)
    out = []
    # 住所欄の開始桁(そのページで一番多いもの)
    pos = []
    for l in lines:
        if not num.match(l): continue
        m = ADDR.search(l)
        if m: pos.append(dpos(l, m.start()))
    if not pos: return out
    acol = sorted(pos)[len(pos)//2]
    for i, l in enumerate(lines):
        m = num.match(l)
        if not m: continue
        a = ADDR.search(l)
        if not a or abs(dpos(l, a.start()) - acol) > 12: continue
        # ⚠ 名称の切れ目は**その行の住所の位置**で切る(ページの代表桁で切ると名称に住所が食い込む)
        head = l[:a.start()]
        name = re.sub(num, '', head).strip()
        rest = [x for x in re.split(r'\s{2,}', l[a.start():].strip()) if x]
        if not rest: continue
        addr, tail = rest[0], rest[1:]
        area = kind = ''
        if tail:
            mm = re.match(r'^([\d,]+)\s*(.*)$', tail[0])
            if mm: area, kind, tail = mm.group(1), mm.group(2).strip(), tail[1:]
            else: kind, tail = tail[0], tail[1:]
        # 折り返した名称(上下の行で、名称の桁に収まっているもの)
        for j in (i-1, i+1):
            if not (0 <= j < len(lines)): continue
            x = lines[j]
            if not x.strip() or num.match(x): continue
            if ADDR.search(x): continue
            # ⚠ 折り返した名称は**住所の桁をまたいで伸びる**ことがある(外濠公園の例)。
            #   右端では判定できないので「左端が名称欄にある・欄が1つしかない」で見る
            s0 = dpos(x, len(x) - len(x.lstrip()))
            if 1 <= s0 < acol - 2 and len(re.split(r'\s{2,}', x.strip())) == 1:
                name = (x.strip() + name) if j < i else (name + x.strip())
        out.append({'no': int(m.group(1)), 'n': name, 'a': addr, 's': area.replace(',', ''),
                    'k': kind, 'rm': ' '.join(tail)})
    return out


def pages(txt):
    out, cur = [], []
    for l in txt.split('\n'):
        if l.startswith('\x0c') and cur: out.append(cur); cur = []
        cur.append(l)
    out.append(cur)
    return out


# ── 都県ごと ────────────────────────────────────────────────────────
def tokyo():
    """東京都地域防災計画 震災編(令和5年修正) 別冊1資料編 資料2-6-7 災害時臨時離着陸場候補地一覧"""
    t = pdftext('https://www.bousai.metro.tokyo.lg.jp/_res/projects/default_project/_page_/001/000/359/2023_b11.pdf', 'tokyo_b11')
    L = t.split('\n')
    st = max(i for i, l in enumerate(L) if '災害時臨時離着陸場候補地一覧' in l)
    en = next(i for i in range(st+5, len(L)) if re.search(r'資\s*料\s*2-6-8', L[i]))
    rows = []
    for pg in pages('\n'.join(L[st:en])): rows += rows_by_columns(pg)
    return rows, dict(pref='東京都', src='東京都地域防災計画 震災編(令和5年修正) 資料2-6-7 災害時臨時離着陸場候補地一覧',
                      yr='令和5年(2023)')


PARSERS = {13: tokyo}


# ── 突合とジオコーディング ────────────────────────────────────────────
def norm(s):
    s = unicodedata.normalize('NFKC', s or '')
    s = re.sub(r'[\s　（）()・「」【】]', '', s)
    return s.replace('ヶ', 'ケ').replace('ヵ', 'ケ').replace('第', '').replace('都立', '').replace('立', '')


def akey(a):
    """住所を「区市町村＋町名」までに丸めた突合キー(丁目・番地は資料で書き方が違う)"""
    a = unicodedata.normalize('NFKC', a or '')
    a = re.sub(r'[\s　]', '', a)
    m = re.match(r'(.*?[区市町村])(.*)', a)
    if not m: return a
    town = re.split(r'[0-9]', m.group(2))[0]
    town = re.sub(r'(丁目|番地|番|地内|地先|先|字)$', '', town)
    return m.group(1) + town[:6]


def geocode(q):
    try:
        b = urllib.request.urlopen(urllib.request.Request(GSI + urllib.parse.quote(q), headers=UA), timeout=30).read()
        j = json.loads(b)
        if j: return round(j[0]['geometry']['coordinates'][1], 6), round(j[0]['geometry']['coordinates'][0], 6)
    except Exception: pass
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry' in sys.argv
    codes = [int(a) for a in args] if args else sorted(PARSERS)
    base = json.load(open(os.path.join(HERE, '..', 'helipad.json')))
    out = json.load(open(os.path.join(HERE, '..', 'helipad_pref.json'))) if \
        os.path.exists(os.path.join(HERE, '..', 'helipad_pref.json')) else {'p': {}}
    for c in codes:
        rows, meta = PARSERS[c]()
        # N11 の同じ都県の点(prc は入れていないので、都県名で住所から絞る)
        old = [x for x in base['f'] if x.get('p') == c]   # N11 の都道府県コードで絞る
        # ⚠ 名称の書き方が資料ごとに違う(「区立麻布野球場」/「港区立麻布運動場・野球場」)。
        #   **住所の町名まで**で候補を絞ってから名称の近さで選ぶ
        import difflib
        oi = {}
        for x in old: oi.setdefault(akey(x.get('a')), []).append(x)
        hit = miss = 0
        recs, recs_new = [], []
        for r in rows:
            if not r['n'] or not r['a']: continue
            cand = oi.get(akey(r['a'])) or []
            best = None
            if cand:
                if len(cand) == 1: best = cand[0]
                else:
                    sc = [(difflib.SequenceMatcher(None, norm(r['n']), norm(x['n'])).ratio(), x) for x in cand]
                    sc.sort(key=lambda t: -t[0])
                    if sc[0][0] >= 0.35: best = sc[0][1]
            cand = [best] if best else None
            rec = {'n': r['n'], 'a': r['a']}
            if r['s']: rec['s'] = r['s'] + '㎡'
            if r['k']: rec['kt'] = r['k']
            if r['rm']: rec['rm'] = r['rm']
            if cand:
                rec['lat'], rec['lng'] = cand[0]['lat'], cand[0]['lng']; rec['o'] = 1; hit += 1
            else:
                miss += 1; recs_new.append(r)
                if not dry:
                    g = geocode(r['a']) or geocode(re.sub(r'[0-9０-９\-－‐ー丁目番地先字]+$', '', r['a']))
                    time.sleep(1.1)
                    if g: rec['lat'], rec['lng'] = g; rec['g'] = 1
            if 'lat' in rec: recs.append(rec)
        print(f"  {meta['pref']}: 一覧 {len(rows)} 件 / N11と一致 {hit} / 新規 {miss} → 収録 {len(recs)}")
        if dry:
            print('   新規(ジオコーダ行き)の例:', [r['n'] for r in recs_new][:10])
            continue
        out['p'][str(c)] = {'pref': meta['pref'], 'src': meta['src'], 'yr': meta['yr'], 'f': recs}
    if dry: return
    dst = os.path.join(HERE, '..', 'helipad_pref.json')
    json.dump(out, open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    n = sum(len(v['f']) for v in out['p'].values())
    print(f'{n} 件 / {len(out["p"])} 都県 → helipad_pref.json ({os.path.getsize(dst)/1024:.0f}KB)')


if __name__ == '__main__':
    main()
