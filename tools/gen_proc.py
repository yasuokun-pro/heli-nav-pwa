#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飛行方式一覧 生成 (proc.json)
============================
出典: AIP Japan 各飛行場 **AD 2.24 CHARTS RELATED TO AN AERODROME** の索引ページ。
SID / STAR / 計器進入(IAC) の**名前と種別だけ**を取る。形(経路)は図なので取らない。

使い方:
  python3 tools/gen_proc.py           # proc.json を出力

⚠ 索引の書式(2026-09 に確認・113空港)
  - "Standard Departure Chart - Instrument (VAMOS-RNAV)"  → SID。名前に RNAV が入れば RNAV SID
  - "Standard Arrival Chart - Instrument (OSHIMA-1A/1K/2C-RNAV)" → STAR
  - "Instrument Approach Chart (ILS Z RWY34L)" → IAC。先頭語が種別:
      ILS 165 / RNP 217 / VOR 147 / TACAN 60 / LOC 44 / LDA 8 / RNAV 6 / HI-ILS 5 /
      RNAV(GPS) 4 / VOR/DME 2 / HI-VOR 2 / HI-TACAN 2 / GLS 2 (全国の枚数)
  - ⚠ 図そのもの(DA/MDA/RVR)は本文レイヤが文字化け混じりで取れない(RJTT AD2-259 で確認)。
    ミニマは別途、手で表を持つか諦める
"""
import os, re, sys, json, glob, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
KIND = [('Standard Departure Chart', 'SID'), ('Standard Arrival Chart', 'STAR'),
        ('Instrument Approach Chart', 'IAC')]
TYP = re.compile(r'^(HI-ILS|HI-VOR|HI-TACAN|ILS|LOC|LDA|VOR/DME|VOR|TACAN|NDB|RNP|RNAV\(GPS\)|RNAV|GLS)\b')


def pdfs():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine/*.pdf',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine/*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f:
            # ⚠ 日付フォルダが複数あると全AIRACのPDFが混ざる(2026-09 に踏んだ)。最新の日付フォルダだけ
            latest = max(os.path.basename(os.path.dirname(os.path.dirname(x))) for x in f)
            return [x for x in f if os.path.basename(os.path.dirname(os.path.dirname(x))) == latest]
    return []


def known_points():
    """IAF ラベルの検証用: FIX名(fix.json)と navaid ID(navaids.gen.js)。無ければ検証なし"""
    names = set()
    try:
        for f in json.load(open(os.path.join(HERE, '..', 'fix.json')))['f']:
            names.add(f['n'])
            if f.get('id'): names.add(f['id'])
    except FileNotFoundError: pass
    try:
        js = open(os.path.join(HERE, 'navaids.gen.js'), encoding='utf-8').read()
        for a in json.loads(js[js.index('['):js.rindex(']')+1]):
            if a.get('id'): names.add(a['id'])
    except (FileNotFoundError, ValueError): pass
    return names

KNOWN = None
MINIMA = {}
IAF_RE = re.compile(r'([A-Z]{2,7})\s*\(IAF[^)]{0,10}\)')

def iaf_by_page(txt):
    """各 IAC ページの "TOHNE(IAF)" ラベルを集める → {IAC番号: [FIX名…]}
    ⚠ ページ番号は脚注の "RJTL AD2.24-IAC-2" から。索引の IAC の並び順と同じ番号(n番目)
    ⚠ 図の文字化け(数字が \x13… に化ける)は名前には及ばない。ただし "KIAS" "RNAV1" のような語も
      "(IAF)" の前に来ることがあるので、FIX名か navaid ID として実在するものだけ採る"""
    global KNOWN
    if KNOWN is None: KNOWN = known_points()
    res = {}
    for pg in txt.split('\f'):
        m = re.search(r'AD\s?2\.24-IAC-(\d+)', pg)
        if not m: continue
        n = int(m.group(1))
        names = []
        for nm in IAF_RE.findall(pg):
            if (not KNOWN or nm in KNOWN) and nm not in names: names.append(nm)
        if names: res.setdefault(n, [])
        for nm in names:
            if nm not in res[n]: res[n].append(nm)
    return res


def _shift(s):
    """埋め込みフォントの文字コードは一律 29 小さい('&LUFOLQJ'→'Circling'、\x03→空白、\x14→'1')"""
    return ''.join(chr(ord(c) + 29) if 0x03 <= ord(c) <= 0x5e else c for c in s)


KW = ('CAT', 'LOC', 'CIRCLING', 'MINIMA', 'RVR', 'VIS', 'MDA', 'DA(H)', 'ILS', 'RNP', 'VOR', 'TACAN',
      'NDB', 'RWY', 'APCH', 'Circling', 'not', 'gradient', 'authorized', 'established')


def _shifted(seg, ctl=True):
    """この断片が化けているか。制御文字を含む、または(その塊に化けがある時だけ)29足すと表の語になる。
    ⚠ 語だけで判定すると、化けていない表の数字まで変換しうる。ctl で塊ごとに歯止めを掛ける"""
    if any(0x01 <= ord(c) <= 0x1c for c in seg): return True
    if not ctl or len(seg) < 3: return False
    sh = _shift(seg)
    return any(k in sh for k in KW) and not any(k in seg for k in KW)


def dec(s):
    """図の文字化けを戻す。
    ⚠ **1行がまるごと化けているとは限らない**(羽田 IAC-10 の注記は末尾の " 34L." だけ生のまま)。
      化けた文字列は空白を \x03 で持つので、**本物の空白(0x20)で区切った断片ごと**に判定して戻す。
      断片ごとにしないと、生の部分まで 29 ずれて "RWY=PQiK" のような文字列になる
      (行全体を戻していた時、空白の並びが '====' になっていたのも同じ原因)。
    ⚠ 合字・別フォントの化け: 䱶/䊠=I 䱷=II 䱸=III 凬=: 䯍=– 䤑=°"""
    ctl = any(0x01 <= ord(c) <= 0x1c for c in s if c != '\n' and c != '\t')
    out = []
    for line in s.split('\n'):
        parts = re.split(r'( +)', line)
        line = ''.join(p if p.strip() == '' or not _shifted(p, ctl) else _shift(p) for p in parts)
        for x, y in (('䱸', 'III'), ('䱷', 'II'), ('䱶', 'I'), ('䊠', 'I'), ('凬', ':'), ('䯍', '–'), ('䤑', '°')):
            line = line.replace(x, y)
        # もう一つの化け方: CJK面 0x4883〜0x4901 は **ord-0x4882 がそのままASCII**(䢲='0' 䣇='E' 䢢=空白)
        out.append(''.join(chr(ord(c) - 0x4882) if 0x4883 <= ord(c) <= 0x4901 else
                           ('?' if 0x3400 <= ord(c) <= 0x9fff else c) for c in line))
    return '\n'.join(out)


def minima_by_page(txt):
    """各 IAC ページの MINIMA 表(DA(H)/MDA(H)/RVR/VIS を分類 A〜D ごとに書いた表)を**原文のまま**集める。
    セルが結合された表で機械的な解釈が危ないので、数値には直さず <pre> で見せる。
    ⚠ 以前「本文レイヤから取れない」と判断したのは数字が \x13… に化けていたため。dec() で戻せる"""
    res = {}
    for pg in txt.split('\f'):
        m = re.search(r'AD\s?2\.24-IAC-(\d+)', pg)
        if not m: continue
        L = dec(pg).split('\n')
        # ⚠ "MINIMA" は CHANGE 行(改正内容の要約)や表の下の注記にも出る。
        #   表の見出しは "MINIMA … THR elev." の行。無ければ直後に CAT 行が続くものを採る
        cand = [i for i, l in enumerate(L) if re.search(r'\bMINIMA\b', l) and 'CHANGE' not in l]
        st = next((i for i in cand if 'elev' in L[i]), None)
        if st is None:
            st = next((i for i in cand if any(re.search(r'\bCAT\b', x) for x in L[i+1:i+6])), None)
        if st is None: continue
        blk = []
        # ⚠ CHANGE 行(改正内容)が**見出しと表の行の間に挟まる**ことがある(成田 IAC-11)。
        #   そこで切ると表が丸ごと落ちるので、CHANGE 行は飛ばすだけにして、切るのは脚注だけにする
        for l in L[st:st+40]:
            if re.search(r'Civil Aviation Bureau|AIP Japan', l): break
            if re.search(r'CHANGE\s*:', l): continue
            blk.append(l.rstrip())
        while blk and not blk[-1].strip(): blk.pop()
        blk = [l for k, l in enumerate(blk) if l.strip() or (k and blk[k-1].strip())]
        # 共通の左余白を落とす(幅を節約。列の相対位置は保つ)
        ind = min((len(l) - len(l.lstrip()) for l in blk if l.strip()), default=0)
        res[int(m.group(1))] = '\n'.join(l[ind:] for l in blk)
    return res


END_RE = re.compile(r'\bto\s+([A-Z][A-Z0-9]{2,6})\b')
# ⚠ "…to ANOBU and" と "hold." の間に**別の欄の数字が挟まる**(立川 IAC-1 の "35")。
#   小文字を含まない範囲なら間に何か入っていても続きとみなす
MAH_RE = re.compile(r'((?:[A-Z0-9][A-Z0-9./]*\s+){0,3}[A-Z][A-Z0-9]{2,6})\s+and\s+[A-Z0-9°./\s]{0,60}?hold\b')
MAH_GEN = {'DME', 'VOR', 'VORTAC', 'TACAN', 'NDB', 'VDP', 'SDF', 'MAPT', 'FAF', 'IF', 'THE', 'AND', 'FIX', 'ARC'}


def narr_by_page(txt, kind):
    """SID/STAR の図の説明文から "…via SHT R297 to OMIYA." の **到達点の並び**を拾う。
    ⚠ 索引の方式名は地名や方角のことがある(下総の "WEST" は OMIYA 行き)。名前だけでは経路に繋げない。
    ⚠ 出発飛行場自身の navaid も "to SHT TACAN" の形で混ざるので、**使う側で近すぎる点を捨てる**"""
    global KNOWN
    if KNOWN is None: KNOWN = known_points()
    res = {}
    for pg in txt.split('\f'):
        m = re.search(r'AD\s?2\.24-' + kind + r'-(\d+)', pg)
        if not m: continue
        L = [dec(l) for l in pg.split('\n')]
        nar = ' '.join(l.strip() for l in L if re.search(r'RWY\d+\s*:|proceed|intercept|via |Cross ', l))
        seen = []
        for x in END_RE.findall(nar):
            if (not KNOWN or x in KNOWN) and x not in seen: seen.append(x)
        if seen: res[int(m.group(1))] = seen
    return res


def mah_by_page(txt):
    """進入図の "SHT R346 to TOHNE and hold." = ミスドアプローチの待機点"""
    global KNOWN
    if KNOWN is None: KNOWN = known_points()
    res = {}
    for pg in txt.split('\f'):
        m = re.search(r'AD\s?2\.24-IAC-(\d+)', pg)
        if not m: continue
        nar = ' '.join(dec(l).strip() for l in pg.split('\n'))
        # ⚠ 待機点は ENR 4.3 に無い進入固有の点のこともある(館山の LULKU)。名前は拾って持ち、
        #   地図に置けるかは使う側で判断する
        x = MAH_RE.search(nar)
        if not x: continue
        ph = re.sub(r'\s+', ' ', x.group(1)).strip()
        last = ph.split()[-1]
        # 地図に置ける点(FIX/navaid)なら name、置けない書き方("TET 15 DME" 等)は文字だけ残す
        res[int(m.group(1))] = (last, ph) if (last not in MAH_GEN and (not KNOWN or last in KNOWN)) else (None, ph)
    return res


def parse_one(pdf):
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
    icao = os.path.basename(pdf)[:4]
    L = txt.split('\n'); out = []; on = False
    # ⚠ 長い名前は索引でも2行に折れる("(OSHIMA, AKSEL,\n AROSA-2H-RNAV)")。閉じ括弧が無ければ次行を継ぐ
    J = []
    for l in L:
        if J and '(' in J[-1] and ')' not in J[-1] and any(k in J[-1] for k, _ in KIND):
            J[-1] = J[-1].rstrip() + ' ' + l.strip()
        else: J.append(l)
    L = J
    gap = 0
    for l in L:
        if 'AD 2.24' in l and 'CHARTS RELATED' in l: on = True; continue
        if not on: continue
        # ⚠ 索引は2ページにまたがることがある(RJTTなど)。ページの脚注で切らず、
        #   一覧が始まったあと該当行が15行続けて無くなったら終わりとみなす
        if re.search(r'AD 2\.25', l) and out: break
        if any(key in l for key, _ in KIND): gap = 0
        elif out:
            gap += 1
            if gap > 15: break
        for key, k in KIND:
            if key in l:
                # ⚠ 末尾に '*'(脚注印)が付く行がある(RJCC は 34枚中 20枚)。閉じ括弧の後の * は無視
                m = re.search(r'\((.*)\)\s*\**\s*$', l.strip())
                if m: name = m.group(1).strip()
                else:
                    # ⚠ 自衛隊系(築城・美保・小松島・三沢・防府北など)は方式名を索引に書かず
                    #   "Standard Departure Chart - Instrument-1" のように枚数だけ。名前は図にしかない
                    ms = re.search(key + r'\s*-?\s*Instrument\s*-?\s*(\d)?\s*$', l.strip())
                    if not ms and not re.search(key + r'\s*$', l.strip()): continue
                    name = ('#' + ms.group(1)) if ms and ms.group(1) else '#'
                rec = {'icao': icao, 'k': k, 'n': name}
                if name.startswith('#'): rec['nn'] = 1          # 索引に名前が無い(図参照)
                if 'RNAV' in name or 'RNP' in name: rec['rnav'] = 1
                if k == 'IAC':
                    mt = TYP.match(name)
                    if mt: rec['typ'] = mt.group(1)
                    mr = re.search(r'RWY\s*(\d{2}[LRC]?)', name)
                    if mr: rec['rwy'] = mr.group(1)
                    if 'CAT II' in name or 'CAT III' in name: rec['cat'] = 'II/III'
                    if 'HELI' in name.upper() or 'COPTER' in name.upper(): rec['heli'] = 1
                out.append(rec)
    # 進入図の IAF を、索引の IAC の n 番目に対応づける(AD2.24-IAC-n)
    iaf = iaf_by_page(txt)
    iacs = [r for r in out if r['k'] == 'IAC']
    for n, names in iaf.items():
        if 1 <= n <= len(iacs): iacs[n-1]['iaf'] = names
    # ミニマ表(原文)は別ファイル(iacmin.json)。proc.json 側には「あり」の印だけ
    for n, blk in minima_by_page(txt).items():
        if 1 <= n <= len(iacs): iacs[n-1]['mn'] = 1; MINIMA[f"{icao}|{n}"] = blk
    for n, (nm, ph) in mah_by_page(txt).items():
        if 1 <= n <= len(iacs):
            if nm: iacs[n-1]['mah'] = nm
            iacs[n-1]['mahT'] = ph
    # SID/STAR の図の到達点(索引の名前が地名・方角でも経路に繋げるように)
    for kind in ('SID', 'STAR'):
        ks = [r for r in out if r['k'] == kind]
        for n, names in narr_by_page(txt, kind).items():
            if 1 <= n <= len(ks): ks[n-1]['to'] = names
    return out


def main():
    fs = pdfs()
    if not fs: print('AD2のPDFが無い', file=sys.stderr); sys.exit(1)
    out = []
    for f in fs: out += parse_one(f)
    eff = os.path.basename(os.path.dirname(os.path.dirname(fs[0])))
    dst = os.path.join(HERE, '..', 'proc.json')
    json.dump({'eff': eff, 'src': 'AIP Japan AD 2.24 索引', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    dst2 = os.path.join(HERE, '..', 'iacmin.json')
    json.dump({'eff': eff, 'src': 'AIP Japan AD 2.24 IAC MINIMA(原文抜粋)', 'f': MINIMA},
              open(dst2, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f"  ミニマ表 {len(MINIMA)} 図 → iacmin.json ({os.path.getsize(dst2)/1024:.0f}KB)")
    ap = len(set(x['icao'] for x in out))
    c = {k: sum(1 for x in out if x['k'] == k) for _, k in KIND}
    ni = sum(1 for x in out if x.get('iaf')); nt = sum(1 for x in out if x.get('to')); nm = sum(1 for x in out if x.get('mah'))
    print(f"{ap} 空港 SID {c['SID']} / STAR {c['STAR']} / IAC {c['IAC']}(IAF {ni} / ミスド待機 {nm}) ・ 図の到達点 {nt} → proc.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}")


if __name__ == '__main__':
    main()
