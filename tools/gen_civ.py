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
import re, os, sys, glob, subprocess, json

# 地域コードは表の見出し(Kanto/Koshinetsu Area (KK) 等)そのまま。
# KK=関東/甲信越、CK=中部/近畿、CS=中国/四国。字面から推測すると間違える
REGION = {'HK': '北海道', 'TH': '東北', 'KK': '関東/甲信越', 'CK': '中部/近畿',
          'CS': '中国/四国', 'KS': '九州', 'SM': '下地島'}
NOISE = re.compile(r'AIP Japan|Civil Aviation|^ENR 5\.|Name\s+Area|TRAINING TESTING')


def dms(s):
    m = re.match(r'(\d{2})(\d{2})(\d{2})N/?(\d{3})(\d{2})(\d{2})E', s)
    return [round(int(m.group(1)) + int(m.group(2))/60 + int(m.group(3))/3600, 5),
            round(int(m.group(4)) + int(m.group(5))/60 + int(m.group(6))/3600, 5)]


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
            pts += [dms(g) for g in re.findall(r'\d{6}N/\d{7}E', ln)]
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
        blocks.append({'rg': region, 'n': ids[0] if ids else '', 'ids': ids, 'pts': pts,
                       'rmk': re.sub(r'\s+', ' ', ' '.join(rmk))[:220],
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
                    'inh': inh})

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
