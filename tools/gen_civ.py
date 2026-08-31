#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
民間訓練試験空域 生成 (civ.json)
================================
出典: AIP Japan **ENR 5.3.1 民間訓練試験空域**
      (TRAINING TESTING AREA FOR CIVIL AIRCRAFT)

技能証明実地試験・耐空証明・社内試験・訓練飛行等に使う空域。
使用にはATMセンターへの訓練計画の提出と承認が必要(ENR 5.3.1.1)。
通過するだけなら提出不要だが、Controlling / Communication Facility への連絡が要る。
訓練機がいる空域なので、VFRで横切るときは在否の確認が要る＝地図に出す価値がある。

パース方針:
  pdftotext -layout の**列位置**が安定している表なので、それを使う。
    x<20        … 空域番号(1-1 等)
    x 20〜95    … 座標・記述
    x 96〜109   … 上限高度(FL200 / 5000 等。下限は全てSFC)
    x>=110      … 使用時間・管制機関
  高度セルは区画の行範囲の中に現れるので、行番号の近さで対応づける。

出力: civ.json {"eff":..,"f":[{rg,n,up,fac,pts:[[lat,lng],..]},..]}
  rg=地域 n=空域番号 up=上限ft(FLは100倍で格納) lo=下限ft(0=SFC) fac=管制/通信機関
使い方: python3 tools/gen_civ.py
AIRAC更新のたびに再実行し、区画数と上限高度の差分を確認すること。
"""
import re, os, sys, glob, subprocess, json, math

# 地域コードは表の見出し(Kanto/Koshinetsu Area (KK) 等)そのまま。
# KK=関東/甲信越、CK=中部/近畿、CS=中国/四国。字面から推測すると間違える
REGION = {'HK': '北海道', 'TH': '東北', 'KK': '関東/甲信越', 'CK': '中部/近畿',
          'CS': '中国/四国', 'KS': '九州', 'SM': '下地島'}
NOISE = re.compile(r'AIP Japan|Civil Aviation|^ENR 5\.|Name\s+Area|TRAINING TESTING')


def dms(s):
    m = re.match(r'(\d{2})(\d{2})(\d{2})N/?(\d{3})(\d{2})(\d{2})E', s)
    return [round(int(m.group(1)) + int(m.group(2))/60 + int(m.group(3))/3600, 5),
            round(int(m.group(4)) + int(m.group(5))/60 + int(m.group(6))/3600, 5)]



# ══════════════════════════════════════════════════════════
# 形状指定(円弧・除外円)の反映
# ══════════════════════════════════════════════════════════
# ENR 5.3.1 は座標表のあとに文章で形を補足している。
#   「The line connecting point (3) and (4) is minor arc with a radius of
#     45NM from Hakodate VOR/DME (HWE).」
#   「Excluding the airspace within 13NM radius of Sapporo Aerodrome/RJCO
#     (430703N/1412253E).」
# ⚠ **折り返された行を繋いで全文にしないと中心が落ちる**(「radius of 45NM」で
#   切れて次行が「from Hakodate VOR/DME (HWE).」)。blocks の 'desc' がその全文。
# ⚠ **公称半径で描いてはいけない**。AIPの頂点は公称半径から最大1NMずれる
#   (KK1-1の(3)は20NM弧のはずが19.0NM)。原因は中心のずれで、
#   GTC/HWEの弧上の点を当てはめると **公表のVOR位置から0.2NM離れた点**で
#   RMS 0.02NM に収まる(公表位置のままだと0.12〜0.16NM)。
#   → **半径を両端で線形補間して、AIPの頂点を必ず通す**(gen_asp.arc_between と同じ)
CIV_ARC = re.compile(
    r'The lines? connecting ((?:point\s*)?\(\d+\)(?:\s*(?:and|to)\s*(?:point\s*)?\(\d+\),?\s*)+)'
    r'(?:is|are)\s+(?:the\s+)?(minor|major)?\s*arcs?\s+(?:with a radius of|within)\s*'
    r'([\d.]+)\s*NM\s*(?:radius\s*)?(?:from|of)?\s*([^.]*)\.', re.I)
CIV_EXC = re.compile(
    r'Excluding the airspaces? within\s*([\d.]+)\s*NM\s*(?:radius\s*)?(?:of)?\s*([^.]*?)\.', re.I)
COORD = re.compile(r'(\d{6})N\s*/?\s*(\d{7})E')

# KGE(加治木VOR/DME)は ENR 4.1 にも各AD 2.19 にも無い。
# 九州4-5-30/4-6-25/4-7 の 13NM・25NM 弧の4点から中心を当てはめて決めた
# (RMS 0.015NM)。**ENR 4.4のFIX 3つ(HIGOH 027°/25.4NM・ISKID 226°/15.5NM・
# JINGU 076°/17.6NM、いずれも磁方位)を方位0.1°・距離0.0NMで再現する**ので確か
CIV_EXTRA_NAV = {'KGE': (31.79809, 130.72563)}


def load_navaids(here):
    nav = dict(CIV_EXTRA_NAV)
    f = os.path.join(here, 'navaids.gen.js')
    if os.path.exists(f):
        for m in re.finditer(r'"id":"([A-Z]{2,4})"[^}]*?"lat":([\d.]+),"lng":([\d.]+)', open(f).read()):
            nav.setdefault(m.group(1), (float(m.group(2)), float(m.group(3))))
    return nav


def resolve_ctr(txt, nav):
    """『Hakodate VOR/DME (HWE)』『RJCO (430703N/1412253E)』→ (lat,lon)"""
    m = COORD.search(txt.replace(' ', ''))
    if m:
        return (round(int(m.group(1)[0:2]) + int(m.group(1)[2:4])/60 + int(m.group(1)[4:6])/3600, 6),
                round(int(m.group(2)[0:3]) + int(m.group(2)[3:5])/60 + int(m.group(2)[5:7])/3600, 6))
    m = re.search(r'\(([A-Z]{3})\)', txt) or re.search(r'\b([A-Z]{3})\b', txt)
    if m and m.group(1) in nav: return nav[m.group(1)]
    return None


def _nm(a, b):
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    return 2*3440.065*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 +
                                math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2))


def civ_arc(c, a, b, major=False):
    """中心cのまわりで a→b。**半径は両端で線形補間**して頂点を必ず通す"""
    K = math.cos(math.radians(c[0]))
    ax, ay = (a[1]-c[1])*K, a[0]-c[0]
    bx, by = (b[1]-c[1])*K, b[0]-c[0]
    ra, rb = math.hypot(ax, ay), math.hypot(bx, by)
    ta, tb = math.atan2(ax, ay), math.atan2(bx, by)
    d = (tb - ta) % (2*math.pi)
    if (d > math.pi) != bool(major): d -= 2*math.pi        # 短弧/長弧
    n = max(16, int(abs(math.degrees(d))/1.5))
    return [[round(c[0] + (ra+(rb-ra)*i/n)*math.cos(ta+d*i/n), 5),
             round(c[1] + (ra+(rb-ra)*i/n)*math.sin(ta+d*i/n)/K, 5)] for i in range(1, n)]


def apply_shape(f, nav, log):
    """円弧と除外円を反映して f['pts'] を差し替える。効いたら注記を書き換える"""
    desc, pts = f.get('desc', ''), f['pts']
    n = len(pts)
    arcs, bad = {}, []
    for m in CIV_ARC.finditer(desc):
        c = resolve_ctr(m.group(4), nav)
        r = float(m.group(3)); major = (m.group(2) or '').lower() == 'major'
        if not c:
            log.append(f"  ? {f['rg']} {f['n']}: 弧の中心が引けない「{m.group(4)[:40]}」"); continue
        for a, b in re.findall(r'\((\d+)\)\s*(?:and|to)\s*(?:point\s*)?\((\d+)\)', m.group(1)):
            i, j = int(a), int(b)
            if not (1 <= i <= n and 1 <= j <= n) or (j - i) % n != 1:
                bad.append(f'({a})-({b}) が隣り合っていない'); continue
            da, db = _nm(c, pts[i-1]), _nm(c, pts[j-1])
            # ⚠ AIPの頂点は公称半径からずれる(KK1-1の(3)は20NM弧のはずが19.0NM)。
            #   半径を補間して頂点を通すので描画は破綻しない。1.5NMまでは通し、
            #   0.3NM超は警告に出す。それ以上は点番号の読み違いを疑う
            if abs(da-r) > 1.5 or abs(db-r) > 1.5:
                bad.append(f'({a})-({b}) 公称{r}NMに対し {da:.2f}/{db:.2f}NM(見送り)'); continue
            if abs(da-r) > 0.3 or abs(db-r) > 0.3:
                log.append(f"  ! {f['rg']} {f['n']} ({a})-({b}): "
                           f'公称{r}NMに対し {da:.2f}/{db:.2f}NM。AIPの頂点が公称からずれている')
            arcs[i-1] = (c, major)
    if bad: log.append(f"  ✗ {f['rg']} {f['n']}: " + ' / '.join(bad))
    ring = []
    for i in range(n):
        ring.append(pts[i])
        if i in arcs:
            c, major = arcs[i]
            ring += civ_arc(c, pts[i], pts[(i+1) % n], major)
    exc = []
    for m in CIV_EXC.finditer(desc):
        r = float(m.group(1)); tail = m.group(2)
        cs = [(round(int(a[0:2])+int(a[2:4])/60+int(a[4:6])/3600, 6),
               round(int(a2[0:3])+int(a2[3:5])/60+int(a2[5:7])/3600, 6))
              for a, a2 in COORD.findall(tail.replace(' ', ''))]
        if not cs:
            c = resolve_ctr(tail, nav)
            if c: cs = [c]
        if not cs:
            log.append(f"  ? {f['rg']} {f['n']}: 除外円の中心が引けない「{tail[:40]}」"); continue
        exc += [(c, r) for c in cs]
    if not arcs and not exc: return 0, 0
    try:
        from shapely.geometry import Polygon, Point
        K = math.cos(math.radians(ring[0][0]))
        g = Polygon([(b*K, a) for a, b in ring]).buffer(0)
        ne = 0
        for c, r in exc:
            # ⚠ **区画をほぼ丸ごと消す除外は、隣の区画の文が紛れ込んだもの**。
            #   ENR 5.3.1は「Within …」で始まる区画があり、行の切り出しで
            #   直前の区画にくっつく(東北12-3に13-1の「50NM of SDE」が入った)。
            #   AIPが区画全体を除外する書き方をするはずがないので弾く
            g2 = g.difference(Point(c[1]*K, c[0]).buffer(r/60.0, quad_segs=32))
            if g2.area < g.area * 0.1:
                log.append(f"  ✗ {f['rg']} {f['n']}: {r}NM除外で9割以上消えるので見送り"
                           f'(隣の区画の文が紛れ込んだ可能性)'); continue
            g = g2; ne += 1
        if g.is_empty: return 0, 0
        if g.geom_type != 'Polygon': g = max(g.geoms, key=lambda q: q.area)
        f['pts'] = [[round(y, 5), round(x/K, 5)] for x, y in g.exterior.coords]
    except ImportError:
        log.append('  shapely が無いので除外円を反映できない'); return len(arcs), 0
    return len(arcs), ne


def main():
    pdf = None
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/ENR_*.pdf',
                '~/Downloads/1_AIP (PDF)/*/ENR_*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: pdf = f[-1]; break
    if not pdf:
        print('ENRのPDFが見つかりません', file=sys.stderr); sys.exit(1)
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'],
                         capture_output=True, text=True).stdout
    i = txt.index('TRAINING TESTING AREA FOR CIVIL AIRCRAFT')
    j = re.search(r'ENR 5\.3\.2|2\. 潜在的な危険', txt[i:])
    seg = txt[i:i + (j.start() if j else 120000)]
    eff = ' / '.join(dict.fromkeys(re.findall(r'EFF:\s*(\d+\s+\w+\s+\d{4})', seg)))

    lines = seg.split('\n')
    # 1) 列位置はページごとに数文字ずれる。見出し行から都度取り直す
    x_alt, x_fac = 96, 117
    alts, facs = {}, {}
    for ln_no, ln in enumerate(lines):
        if 'Altitude' in ln and 'Facility' in ln:
            x_alt = ln.index('Altitude'); x_fac = ln.index('Facility'); continue
        # 高度セルは「上限 / ----- / 下限」の3段。下限はSFCとは限らない
        # (北海道2-1は 8000/4000)。SFCも拾って0として扱う
        for m in re.finditer(r'\b(FL\d{2,3}|\d{3,5}|SFC)\b', ln):
            if not (x_alt - 6 <= m.start() <= x_alt + 8): continue
            v = m.group(1)
            alts.setdefault(ln_no, []).append(
                0 if v == 'SFC' else (int(v[2:]) * 100 if v.startswith('FL') else int(v)))
        # 見出しは列の中央に置かれるが本文は左寄せなので、見出しより左から取る。
        # 高度列の右端(x_alt+12)以降を機関の列とみなすと実データと合う
        f = ln[max(0, min(x_fac - 12, x_alt + 12)):].strip()
        # ページ末尾の日付(9/1/14)や罫線だけの行が混ざるので落とす
        if f and not NOISE.search(f) and not re.fullmatch(r'[\d/\-\.\s]+', f):
            facs[ln_no] = f

    # 2) 区画は「The airspace bounded by …」で始まる。
    #    空域番号(1-3等)は座標の途中の行に置かれることがあり、番号を区切りに
    #    使うと前の区画に座標を取り込んでしまう。必ずこの文言で切ること
    START = re.compile(r'The airspace bounded by')
    starts = [i for i, ln in enumerate(lines) if START.search(ln)]
    blocks, region = [], ''
    for bi, s0 in enumerate(starts):
        s1 = (starts[bi+1] - 1) if bi + 1 < len(starts) else len(lines) - 1
        span = lines[s0:s1+1]
        for ln in span:
            rc = re.search(r'\(([A-Z]{2})\)', ln[:40])
            if rc and rc.group(1) in REGION: region = REGION[rc.group(1)]
        pts, ids, rmk = [], [], []
        for ln in span:
            # ⚠ **弧の中心の座標を頂点に混ぜてはいけない**。
            #   「minor arc with a radius of 5NM of 343548N/1353602E」の座標まで
            #   拾っていて、中部/近畿11-4が8点のはずが26点になっていた。
            #   頂点は必ず「(n) 座標」の形なので、番号が前に付くものだけを採る
            pts += [dms(g) for _, g in re.findall(r'\((\d{1,2})\)\s*(\d{6}N/\d{7}E)', ln)]
            # 番号は名前列に単独で置かれることが多く、行末で終わる場合もある。
            # 「1」のような枝番なしも使われるので、座標を含まない短い行に限り拾う
            m = re.search(r'^[\s\(\)A-Z]{0,24}?\b(\d{1,2}(?:-\d+)+)(?=\s|$)', ln[:42])
            if not m and not re.search(r'\d{6}N', ln) and len(ln.strip()) <= 4:
                m = re.match(r'\s{6,}(\d{1,2})$', ln.rstrip())
            if m: ids.append(m.group(1))
            # 除外区域や円弧の指定は形状に効くが本実装では直線で結んでいるので、
            # 文言をそのまま持って表示する(ポップアップで注意喚起する)
            t = ln[:x_alt].strip()
            if re.match(r'(Excluding|The line connecting|Within )', t): rmk.append(t)
        # ⚠ 形状指定(円弧・除外)は**折り返された行を繋いで全文にしないと
        #   中心が落ちる**。「…radius of 45NM」で切れて次行が「from Hakodate
        #   VOR/DME (HWE).」になっている。説明列だけを繋いで文に割る
        desc = ' '.join(ln[:x_alt].strip() for ln in span if ln[:x_alt].strip())
        desc = re.sub(r'\s+', ' ', desc)
        blocks.append({'rg': region, 'n': ids[0] if ids else '', 'ids': ids, 'pts': pts,
                       'rmk': re.sub(r'\s+', ' ', ' '.join(rmk))[:220], 'desc': desc,
                       's0': s0, 'l0': s0, 'l1': s1})

    # 3) 高度セルを組み立てる。「上限 / ----- / 下限」の2〜3行がひとかたまりで、
    #    離れていれば別のセル。セルの中心行を持っておく
    cells, CELL = [], []
    for l in sorted(alts):
        if cells and l - cells[-1][-1] <= 3: cells[-1].append(l)
        else: cells.append([l])
    for c in cells:
        vs = [v for l in c for v in alts[l]]
        CELL.append({'c': sum(c) / len(c), 'up': max(vs), 'lo': min(vs)})

    # 連絡先も同じく縦結合される(複数区画で1つのセル)。行が続いている間を
    # 1つのまとまりとして扱い、区画には一番近いまとまりを割り当てる
    # 「Controlling / Communication Facility」の見出しが新しいセルの始まり。
    # 行の隙間だけで切ると、隣り合う2つの機関(松本Radioと新千歳Information)が
    # くっついてしまう
    HEAD = re.compile(r'Controll?ing|Communication')
    fcells, FCELL = [], []
    for l in sorted(facs):
        if fcells and l - fcells[-1][-1] <= 2 and not HEAD.search(facs[l]):
            fcells[-1].append(l)
        else: fcells.append([l])
    for c in fcells:
        # 高度セルの罫線(-----)が機関の列にはみ出してくるので落とす
        txt = re.sub(r'-{2,}', ' ', ' '.join(facs[l] for l in c))
        txt = re.sub(r'\s+', ' ', txt).strip(' -')
        if txt: FCELL.append({'c': sum(c) / len(c), 't': txt})

    here0 = os.path.dirname(os.path.abspath(__file__))
    out, nogeom = [], 0
    for b in blocks:
        if len(b['pts']) < 3:
            nogeom += 1     # 新幹線や河川の中心線で定義された区画は座標が無く描けない
            continue
        # 区画の行範囲に高度セルがあればそれ。無ければ**一番近いセル**を採る。
        # AIPは複数区画で高度が同じとき1つのセルを縦結合するので、
        # 値が無い区画は隣の区画と同じ高度帯という意味になる
        # 1つの区画に高度セルが縦に何段も積まれていることがある
        # (東北13-3-4〜13-3-14は同じ形で SFC〜FL140 を11層に分けている)。
        # 地図では同じ形なので、全層をまとめて「下限の最小〜上限の最大」で持つ
        mid = (b['s0'] + b['l1']) / 2
        vals = [v for l, vs in alts.items() if b['s0'] <= l <= b['l1'] for v in vs]
        if vals:
            up, lo, inh = max(vals), min(vals), 0
        elif CELL:
            c = min(CELL, key=lambda c: abs(c['c'] - mid))
            up, lo, inh = c['up'], c['lo'], 1
        else:
            print(f'  {b["rg"]} {b["n"]}: 高度が読めない', file=sys.stderr); continue
        # 連絡先はグループの先頭に印字されるので、区画の中に無ければ
        # 「直前のまとまり」を引き継ぐ(直近の前後で選ぶと次のグループを拾う)
        ins = [c for c in FCELL if b['s0'] <= c['c'] <= b['l1']]
        prev = [c for c in FCELL if c['c'] < b['s0']]
        # 区画の範囲に複数入るときは**後のほう**。前の区画のセルの末尾が
        # 食い込んでいるだけで、その区画の機関は後から始まるため
        fc = ins[-1] if ins else (prev[-1] if prev else (FCELL[0] if FCELL else None))
        fac = fc['t'] if fc else ''
        # 「13-3-4〜13-3-14」のように範囲で書くのは、同じ形に高度セルが
        # 何段も積まれている場合だけ。単に説明文が隣の区画に食い込んだだけの
        # ときに範囲表記すると別空域を1つに見せてしまう
        ncell = sum(1 for c in CELL if b['s0'] <= c['c'] <= b['l1'])
        n = f'{b["ids"][0]}〜{b["ids"][-1]}' if (len(b['ids']) > 1 and ncell > 1) else b['n']
        out.append({'rg': b['rg'], 'n': n, 'nl': len(b['ids']), 'up': up, 'lo': lo,
                    'fac': fac[:70], 'rmk': b.get('rmk', ''), 'pts': b['pts'],
                    'desc': b.get('desc', ''), 'inh': inh})

    # ── 円弧と除外円を反映する ──────────────────────────────
    nav = load_navaids(here0)
    log, na, ne = [], 0, 0
    for f in out:
        a, e = apply_shape(f, nav, log)
        na += a; ne += e
        f['_ar'], f['_ex'] = a, e
    print(f'  円弧 {na}本 / 除外円 {ne}個 を反映')
    for l in log: print(l, file=sys.stderr)

    # 注記を作り直す。⚠ 元は英文をそのまま220字で切っていて**中心も結論も
    #   読めない**断片だった。何を反映して何を近似したかを日本語で出す。
    #   desc(全文)は54KB増えるうえ表示に使わないので出力からは落とす
    APPROX = [('海岸線', r'coastline'), ('河川の中心線', r'center line of'),
              ('支庁界', r'shicho boundary'), ('方位線', r'\d{3}°T from')]
    nap = 0
    for f in out:
        if f.get('osm'): f.pop('desc', None); continue
        desc = f.pop('desc', '')
        pa = [nm for nm, pat in APPROX if re.search(pat, desc, re.I)]
        pt = []
        if f.get('_ar'): pt.append(f"円弧{f['_ar']}本を反映")
        if f.get('_ex'): pt.append(f"除外円{f['_ex']}個を反映")
        if pa: pt.append('／'.join(pa) + 'の区間は直線で近似'); nap += 1
        m = re.search(r'Excluding (?:the airspace )?(?:the |of )?((?:Area |AREA )?[A-Z]{1,2}\d[\w-]*|'
                      r'area of [A-Za-z ]+)', desc)
        if m: pt.append(f'{m.group(1)} の除外は未反映')
        if re.search(r'Maizuru ARP', desc): pt.append('舞鶴ARPの4NM除外は位置不明で未反映')
        f.pop('_ar', None); f.pop('_ex', None)
        f['rmk'] = '。'.join(pt)
    print(f'  海岸線・河川・支庁界で直線近似のまま: {nap}件')

    # KK4は座標ではなく新幹線・河川・道路の中心線で8区分されている。
    # tools/gen_kk4.py が作った形を差し込む(無ければ4-1だけのまま)
    here = os.path.dirname(os.path.abspath(__file__))
    kk4p = os.path.join(here, '..', 'kk4.json')
    if os.path.exists(kk4p):
        base = next((f for f in out if f['rg'] == '関東/甲信越' and f['n'] == '4-1'), None)
        if base:
            i = out.index(base); out.pop(i)
            for k in reversed(json.load(open(kk4p))['f']):
                out.insert(i, {**base, 'n': k['n'], 'pts': k['pts'],
                               'rmk': 'AIPは新幹線・河川・高速道路等の中心線で区分。'
                                      '形状はOSMの線形から再現した目安',
                               'osm': 1})
            print(f'  KK4を {len(json.load(open(kk4p))["f"])} 区分に差し替え')

    dst = os.path.join(here, '..', 'civ.json')
    json.dump({'eff': eff, 'src': 'AIP Japan ENR 5.3.1', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    inh = [f for f in out if f['inh']]
    if inh:
        print(f' 高度セルが縦結合で隣から引き継いだ区画: {len(inh)}件 '
              f'({", ".join(f["rg"]+" "+(f["n"] or "?") for f in inh[:8])}…)')
    print(f'{len(out)} 区画 → civ.json ({os.path.getsize(dst)/1024:.0f}KB) EFF:{eff}')
    import collections
    print(' 地域別:', dict(collections.Counter(f['rg'] for f in out)))
    if nogeom:
        print(f' 座標が無く描けない区画: {nogeom}件'
              f'(新幹線・河川・高速道路の中心線で定義されているもの)')


if __name__ == '__main__': main()
