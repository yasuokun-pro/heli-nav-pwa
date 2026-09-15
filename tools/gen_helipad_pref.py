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
import html, json, os, re, subprocess, sys, time, unicodedata, urllib.request, urllib.parse
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'heli-nav-pwa/1.0'}
CACHE = '/tmp/helipad_pref'
GSI = 'https://msearch.gsi.go.jp/address-search/AddressSearch?q='
# 住所らしい語: 区市町村のあとに数字・丁目・字などが続くもの(施設名の「◯◯区立」を弾く)
ADDR = re.compile(r'[一-龥々ヶケぁ-んァ-ヶー]{1,8}[区市町村](?=[^\s]*(?:[0-9０-９]|丁目|番|字|先|地内))')


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
def rows_muni(lines, city, numbered=r'^\s{0,6}(\d{1,4})\s'):
    """市町村ごとの小表(神奈川の(2)市町村関係型)。
    ⚠ **住所に市町村名が入っていない**(見出しの市名が効いている)ので、住所を語で探せない。
      欄の順(番号+名称 / 所在地 / 東西×南北 / 面積 / 管理者 / 連絡先 / 散水 / ヘリ)で読む。
    ⚠ 面積は「70 × 70 4,900」のように寸法と混ざる。**数字の最大**を面積とみなす"""
    num = re.compile(numbered)
    out = []
    for i, l in enumerate(lines):
        m = num.match(l)
        if not m: continue
        f = [x for x in re.split(r'\s{2,}', l.strip()) if x]
        if len(f) < 2: continue
        name = re.sub(numbered, '', f[0]).strip()
        addr = f[1]
        nums = [int(x.replace(',', '')) for x in f[2:] if re.fullmatch(r'[\d,]{1,9}', x)]
        area = str(max(nums)) if nums else ''
        heli = next((x for x in reversed(f) if x in ('大', '中', '小')), '')
        if not name or not addr: continue
        out.append({'no': int(m.group(1)), 'n': name, 'a': city + addr, 's': area,
                    'k': '臨時離着陸場', 'rm': ('離着陸可能なヘリ: ' + heli) if heli else ''})
    return out


def rows_by_columns(lines, numbered=r'^\s{0,6}(\d{1,4})(?:\s|$)', addr_first=False, pref='', head_drop=0):
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
        if head_drop:   # 名称の前に別の欄がある表(埼玉の 認識番号・消防本部 など)
            hf = [x for x in re.split(r'\s{2,}', name) if x]
            name = ' '.join(hf[head_drop:]) if len(hf) > head_drop else ''
        rest = [x for x in re.split(r'\s{2,}', l[a.start():].strip()) if x]
        if not rest: continue
        addr, tail = rest[0], rest[1:]
        if addr_first:
            # 神奈川の県関係のように **住所が名称より前**に来る表
            if not tail: continue
            name, addr, tail = tail[0], addr, tail[1:]
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
        if pref and not addr.startswith(pref): addr = pref + addr
        out.append({'no': int(m.group(1)), 'n': name, 'a': addr, 's': area.replace(',', ''),
                    'k': kind, 'rm': ' '.join(tail)})
    return out


def words(path, p0, p1):
    """PDFの単語を**実座標つき**で取り出す(ページごとの [(xMin,yMin,xMax,yMax,語), ...])。
    ⚠ pdftotext -layout の桁は全角混在・列の重なりでずれるので、桁で列を切れない表はこちらを使う"""
    o = subprocess.run(['pdftotext', '-bbox-layout', '-f', str(p0), '-l', str(p1), path, '-'],
                       capture_output=True, text=True).stdout
    pg = []
    for m in re.finditer(r'<page width.*?</page>', o, re.S):
        pg.append([(float(a), float(b), float(c), float(d), html.unescape(e))
                   for a, b, c, d, e in re.findall(
                       r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
                       m.group())])
    return pg


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


def kanagawa():
    """神奈川県地域防災計画 マニュアル資料 3-11-(3) 神奈川県内のヘリコプター臨時離着陸場一覧表(令和7年4月1日現在)
    ⚠ 2つの表でできている。(1)県関係は**住所が名称より前**、(2)市町村関係は市ごとの小表で
      **住所に市名が入っていない**(ページ見出しの市名を足す)"""
    t = pdftext('https://www.pref.kanagawa.jp/documents/85490/j3-2.pdf', 'kanagawa_j3-2')
    L = t.split('\n')
    st = next(i for i, l in enumerate(L) if 'ヘリコプター臨時離着陸場一覧' in l)
    # ⚠ 資料番号は全角(資料 ３－11－(4))。ハイフンも全角なので幅を持たせて探す
    en = next(i for i in range(st+20, len(L)) if re.search(r'資料\s*[3３][-－−]\s*11\s*[-－−]\s*[(（]4', L[i]))
    mi = next(i for i in range(st, en) if '市町村関係' in L[i])
    rows = []
    for pg in pages('\n'.join(L[st:mi])): rows += rows_by_columns(pg, addr_first=True)
    # 市町村関係: 「横   浜    市」のような見出しで市が切り替わる
    city = ''
    cur = []
    CITYHD = re.compile(r'^\x0c?\s*(?:[^\s]\s*){1,5}[市町村]\s*$')
    for l in L[mi:en]:
        if CITYHD.match(l.replace('\x0c', '')):
            if city and cur: rows += rows_muni(cur, city)
            city = re.sub(r'[\s\x0c]', '', l); cur = []
        cur.append(l)
    if city and cur: rows += rows_muni(cur, city)
    return rows, dict(pref='神奈川県',
                      src='神奈川県地域防災計画 資料3-11-(3) 神奈川県内のヘリコプター臨時離着陸場一覧表',
                      yr='令和7年(2025)')


def saitama():
    """埼玉県地域防災計画 資料編 Ⅱ-2-4-25 埼玉県内飛行場外離着陸場一覧表(令和2年11月1日現在)
    ⚠ 名称の前に 認識番号・消防本部 の欄がある(head_drop=2)
    ⚠ N11 の埼玉県の点は **住所が空** なので、住所キーではなく名称キーで突合する"""
    t = pdftext('https://www.fdma.go.jp/bousaikeikaku/kanto/saitama/items/02saitama_shiryou.pdf', 'saitama_shiryou')
    L = t.split('\n')
    st = next(i for i, l in enumerate(L) if '埼玉県内飛行場外離着陸場一覧表' in l)
    en = next(i for i in range(st+20, len(L)) if re.search(r'Ⅱ-2-4-2[67]', L[i]))
    rows = []
    for pg in pages('\n'.join(L[st:en])): rows += rows_by_columns(pg, head_drop=2)
    return rows, dict(pref='埼玉県', src='埼玉県地域防災計画 資料編 Ⅱ-2-4-25 埼玉県内飛行場外離着陸場一覧表',
                      yr='令和2年(2020)')


DMS = re.compile(r'(\d{2,3})°\s*(\d{1,2})[′\']\s*([\d.]+)[″"]\s*([NE])')


def dms(m):
    v = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3)) / 3600
    return round(v, 6)


def chiba():
    """千葉県地域防災計画 資料編 資料5-4 ヘリコプター臨時離発着場適地一覧表(令和6年1月1日現在)
    ⚠ この表は **座標(度分秒)が載っている** ので突合もジオコーダも要らない(published が最優先)。
    ⚠ 1件が複数行にまたがる。緯度行(″N)・経度行(″E)が1件に1行ずつあるので「経度行まで」で切る。
    ⚠ 所在地の桁は **行ごとにずれる**(名称が長いと右に押され、名称と空白1個でつながる)ので
      位置では切れない。座標列より左のトークンから「市区町村で始まる語」を得点で選ぶ。"""
    t = pdftext('https://www.pref.chiba.lg.jp/bousai/keikaku/chiikibousai/documents/r6siryo5.pdf', 'chiba_siryo5')
    L = t.split('\n')
    st = next(i for i, l in enumerate(L) if 'ヘリコプター臨時離発着場適地一覧表' in l and '資料５－４' in l)
    en = next(i for i in range(st + 50, len(L)) if re.search(r'＜資料[５5]－[５5-9]|＜資料[６6-9]', L[i]))
    CITY = re.compile(r'^[一-龥々ヶケぁ-んァ-ヶー]{1,8}[区市町村]')
    NUMLN = re.compile(r'^\s{0,3}(\d{1,3})(?:\s|$)')
    rows = []
    for pg in pages('\n'.join(L[st:en])):
        hi = next((i for i, l in enumerate(pg) if '地名・地番' in l and '座標' in l), -1)
        body = pg[hi + 1:]
        # ⚠ 座標列の位置だけは安定しているので、そこから左を「番号+名称+所在地」として扱う。
        #   住所列の開始位置は **行ごとにずれる**(名称が長いと右に押される)ので位置では切れない。
        cs = [dpos(l, m.start()) for l in body for m in [DMS.search(l)] if m]
        if len(cs) < 3: continue
        ccol = Counter(cs).most_common(1)[0][0]
        blk = []
        for l in body:
            blk.append(l)
            if '″E' not in l and '"E' not in l: continue
            txt, blk = '\n'.join(blk), []
            mn = next((m for m in DMS.finditer(txt) if m.group(4) == 'N'), None)
            me = next((m for m in DMS.finditer(txt) if m.group(4) == 'E'), None)
            if not (mn and me): continue
            toks = []          # [文字列, 得点] 得点の高いものを所在地とみなす
            for x in txt.split('\n'):
                nl = bool(NUMLN.match(x))
                d0 = DMS.search(x)
                cut = (dpos(x, d0.start()) if d0 else ccol) - 2   # ⚠ 語は途中で切らない(住所が欠ける)
                for w in re.finditer(r'\S+', x):
                    d, t = dpos(x, w.start()), w.group()
                    if d >= cut: continue
                    if nl and d < 4 and t.isdigit(): continue     # 行頭の通し番号
                    sc = -1
                    if CITY.match(t):
                        sc = 1 * nl + 2 * bool(re.search(r'[0-9０-９]|丁目|番|字', t))
                    toks.append([t, sc])
            adi = max((i for i, t in enumerate(toks) if t[1] >= 0),
                      key=lambda i: (toks[i][1], i), default=None)
            if adi is None: continue
            ad = toks[adi][0]
            nm = ''.join(t[0] for i, t in enumerate(toks) if i != adi).strip()
            sz = re.search(r'(\d{1,4})\s*[×xX]\s*(\d{1,4})', txt)
            kd = re.search(r'\s(大|中|小)\s', txt)
            if not nm or not ad: continue
            rows.append({'n': nm, 'a': ad, 's': '', 'k': kd.group(1) if kd else '',
                         'rm': (sz.group(1) + '×' + sz.group(2) + 'm') if sz else '',
                         'll': (dms(mn), dms(me))})
    return rows, dict(pref='千葉県', src='千葉県地域防災計画 資料編 資料5-4 ヘリコプター臨時離発着場適地一覧表',
                      yr='令和6年(2024)')


def ibaraki():
    """茨城県地域防災計画 資料編 23-1 茨城県防災航空隊離発着場(令和7年3月・PDF p.47-63)
    欄: No / 消防本部別 / 場外・緊急離着陸場(名称) / 市町村 / 地名地番 / 地盤面 / 種別
    ⚠ この表は -layout の桁が当てにならない(名称と市町村の桁が行ごとに重なる)。
      **pdftotext -bbox-layout の実座標**で列を切り、折り返し行は
      「いちばん近い番号のy中心」に付ける(番号は行の上下中央に打たれている)。
    ⚠ 見出しは**最初のページだけ**にあるので、1ページ目で求めた列境界を全ページで使う。
    ⚠ 市町村欄の（旧市町村名）は現在の住所では使えないので落とす。座標は無いのでジオコーダ行き。"""
    f = os.path.join(CACHE, 'ibaraki_shiryo18-25.pdf')
    if not os.path.exists(f):
        get('https://www.pref.ibaraki.jp/seikatsukankyo/bousaikiki/bousai/documents/'
            '4_2025shiryouhen_18-25.pdf', f)
    pg = words(f, 47, 63)
    h = {k: next(w for w in pg[0] if w[4] == k) for k in ('消防本部別', '市町村', '地名地番', '地盤面', '種別')}
    nmx = max(w[2] for w in pg[0] if w[4] in ('場外・緊急', '離着陸場'))
    B = [(h['消防本部別'][2] + 200) / 2, (nmx + h['市町村'][0]) / 2,
         (h['市町村'][2] + h['地名地番'][0]) / 2, (h['地名地番'][2] + h['地盤面'][0]) / 2,
         (h['地盤面'][2] + h['種別'][0]) / 2]
    rows = []
    for pi, ws in enumerate(pg):
        if pi == 0:      # ⚠ 章題と見出しは1ページ目にしかなく、放っておくと1件目に吸われる
            y0 = min(w[1] for w in ws if w[2] < B[0] and re.fullmatch(r'\d{1,4}', w[4]))
            hy = max((w[3] for w in ws if w[1] < y0 - 8), default=0)
            ws = [w for w in ws if w[3] > hy]
        ns = [w for w in ws if w[2] < B[0] and re.fullmatch(r'\d{1,4}', w[4])]
        if not ns: continue
        ns.sort(key=lambda w: w[1])
        own = {}
        for w in ws:
            if w[0] < B[0] or re.search(r'－\s*\d+\s*－|ヶ所', w[4]): continue
            c = (w[1] + w[3]) / 2
            own.setdefault(min(range(len(ns)), key=lambda k: abs((ns[k][1] + ns[k][3]) / 2 - c)),
                           []).append(w)
        for k in sorted(own):
            g = sorted(own[k], key=lambda w: (round(w[1]), w[0]))
            def col(i, j): return ''.join(w[4] for w in g if B[i] <= w[0] < B[j])
            nm = col(0, 1)
            city = re.sub(r'[（(].*', '', col(1, 2))
            ad = col(2, 3)
            if not nm or not city or not ad: continue
            rows.append({'n': nm, 'a': '茨城県' + re.sub(r'\s+', '', city + ad), 's': '',
                         'k': ''.join(w[4] for w in g if w[0] >= B[4]),
                         'rm': '地盤面: ' + col(3, 4) if col(3, 4) else ''})
    return rows, dict(pref='茨城県', src='茨城県地域防災計画 資料編 23-1 茨城県防災航空隊離発着場',
                      yr='令和7年(2025)')


# ⚠ 'ー'(長音)は入れないこと。名称の「ヘリポート」が「ヘリポ-ト」になる
ZEN = str.maketrans('０１２３４５６７８９－―‐ＮＥ／', '0123456789---NE/')


def tochigi():
    """栃木県緊急消防援助隊受援計画(令和2年3月) 別表第10
    ヘリコプター離着陸場所(ランディングポイント)一覧表 (PDF p.41-44)
    ⚠ 地域防災計画 資料編 2-22-2 の方は**那須地区41件の様式見本しか載っていない**。
      県内全域が載っているのはこの受援計画の別表第10。
    ⚠ 名称や区分が1個の空白でつながる行があるので -layout では切れない。**実座標**で列を切る。
    ⚠ 緯度経度は全角(Ｎ３６度３３分５７秒/Ｅ１３９度５３分００秒)。載っているのでジオコーダ不要。"""
    f = os.path.join(CACHE, 'tochigi_juen.pdf')
    if not os.path.exists(f):
        get('https://www.pref.tochigi.lg.jp/kurashi/bousai/kekaku/documents/juennkeikaku.pdf', f)
    B = [114, 171, 216, 290, 368]     # 名称 / 離着陸場所 / 所在地 / 緯度経度 / (地積)
    DM = re.compile(r'N(\d+)度(\d+)分(\d+)秒/?\s*E(\d+)度(\d+)分(\d+)秒')
    rows = []
    for ws in words(f, 41, 44):
        ns = sorted((w for w in ws if w[2] < 40 and re.fullmatch(r'[0-9０-９]{1,4}', w[4])),
                    key=lambda w: w[1])
        if not ns: continue
        y0 = (ns[0][1] + ns[0][3]) / 2 - 8      # ⚠ 見出し行が1件目に吸われるので切り落とす
        own = {}      # ⚠ 緯度と経度が上下の行に割れる件がある。番号のy中心に近い方へ寄せる
        for w in ws:
            if (w[1] + w[3]) / 2 < y0: continue
            c = (w[1] + w[3]) / 2
            own.setdefault(min(range(len(ns)), key=lambda k: abs((ns[k][1] + ns[k][3]) / 2 - c)),
                           []).append(w)
        for k in sorted(own):
            g = sorted(own[k], key=lambda w: (round(w[1]), w[0]))
            def col(a, b): return ''.join(w[4] for w in g if B[a] <= w[0] < B[b])
            t = col(3, 4).translate(ZEN)
            m = DM.search(t) or DM.search(re.sub(r'^(E[^N]*)(N.*)$', r'\2\1', t))
            if not m: continue
            la = int(m.group(1)) + int(m.group(2)) / 60 + int(m.group(3)) / 3600
            lo = int(m.group(4)) + int(m.group(5)) / 60 + int(m.group(6)) / 3600
            nm, ad = col(0, 1), col(2, 3).translate(ZEN)
            if not nm or not ad: continue
            rows.append({'n': nm, 'a': '栃木県' + ad, 's': '', 'k': '', 'rm': col(1, 2),
                         'll': (round(la, 6), round(lo, 6))})
    return rows, dict(pref='栃木県',
                      src='栃木県緊急消防援助隊受援計画 別表第10 ヘリコプター離着陸場所一覧表',
                      yr='令和2年(2020)')


def gunma():
    """群馬県地域防災計画 資料編 12-5 / 緊急消防援助隊受援計画 別表第10 ヘリコプター離着陸場所
    (群馬県防災航空隊管理データ・HB/FB含む)
    ⚠ 出典PDF(消防庁 地域防災計画DB の 03_gunma_shiryou.pdf)は **約135MB** ある。
      一度落としたら /tmp/helipad_pref に残るので消さないこと。
    ⚠ 1件1行。座標は度分秒だが **分の記号が ″ になっている行**(139°05″41″)や
      **全角数字が混ざる行**(36°3４′２２″)があるので、数字を半角化してから緩く拾う。
    ⚠ 見出し【別表第１０】が各ページに出るので、終わりは【別表第１１】で見る。"""
    t = pdftext('https://www.fdma.go.jp/bousaikeikaku/kanto/gunma/items/03_gunma_shiryou.pdf',
                'gunma_shiryou')
    L = t.split('\n')
    st = next(i for i, l in enumerate(L) if '【別表第１０】' in l)
    en = next(i for i in range(st + 50, len(L)) if '【別表第１１】' in L[i])
    ROW = re.compile(r'^\s*(\S+-\d{1,3})\s+(.+?)\s+'
                     r'(\d{1,3})°\s*(\d{1,2})\s*[′″\'"]\s*(\d{1,2})\s*[′″\'"]\s+'
                     r'(\d{1,3})°\s*(\d{1,2})\s*[′″\'"]\s*(\d{1,2})\s*[′″\'"]\s+(.*)$')
    AD = re.compile(r'[一-龥々ヶケぁ-んァ-ヶー]{1,8}[市町村][^\s]*')
    rows = []
    for l in L[st:en]:
        m = ROW.match(l.translate(ZEN).replace('＊', '*'))
        if not m: continue
        la = int(m.group(3)) + int(m.group(4)) / 60 + int(m.group(5)) / 3600
        lo = int(m.group(6)) + int(m.group(7)) / 60 + int(m.group(8)) / 3600
        tail = m.group(9)
        a = AD.search(tail)
        if not a: continue
        sz = re.search(r'(\d{1,4})\s*\*\s*(\d{1,4})', tail)
        rows.append({'n': m.group(2).strip(), 'a': '群馬県' + a.group(), 's': '',
                     'k': '', 'rm': (sz.group(1) + '×' + sz.group(2) + 'm') if sz else '',
                     'll': (round(la, 6), round(lo, 6))})
    return rows, dict(pref='群馬県',
                      src='群馬県地域防災計画 資料編 別表第10 ヘリコプター離着陸場所(群馬県防災航空隊)',
                      yr='令和5年(2023)')


PARSERS = {13: tokyo, 14: kanagawa, 11: saitama, 12: chiba, 8: ibaraki, 9: tochigi, 10: gunma}


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
        oi, ni = {}, {}
        for x in old:
            if x.get('a'): oi.setdefault(akey(x['a']), []).append(x)
            ni.setdefault(norm(x['n']), []).append(x)   # ⚠ N11は県によって住所が空(埼玉は全件None)
        hit = miss = 0
        recs, recs_new = [], []
        for r in rows:
            if not r['n'] or not r['a']: continue
            cand = oi.get(akey(r['a'])) or ni.get(norm(r['n'])) or []
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
            if r.get('ll'):
                # ⚠ キーは 'pc'。'c' は index.html 側で航空法上の分類に使っているので衝突させない
                rec['lat'], rec['lng'] = r['ll']; rec['pc'] = 1; hit += 1
            elif cand:
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
