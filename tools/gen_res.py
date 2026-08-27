#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
制限空域・警戒区域 生成 (res.json)
==================================
出典: AIP Japan **ENR 5.1 禁止、制限及び危険区域**
  ENR 5.1.1 飛行禁止区域 … 現在 Nil
  ENR 5.1.2 飛行制限区域 … RJR1〜3(航空法80条。円形で定義)
  ENR 5.1.3 危険区域     … 現在 Nil
  ENR 5.1.4 空域制限     … R-nnn/W-nnn の演習場・射爆撃場・空戦訓練区域(約40)

**航空法80条に基づく進入禁止空域(RJR)と、射撃・爆撃が行われる区域**なので、
これまでのレイヤー(訓練空域・施設)とは危険度の性質が違う。UIでも別扱いにする。

  ⚠ 上限/下限・使用時間は区域ごとにバラバラで、NOTAMで運用されるものが多い。
    「by NOTAM」の区域は**AIPだけでは可否が判断できない**。UIに必ずその旨を出す。

パースの方針(pdftotext -layout の段組を列位置で分ける):
  col  0〜29 … 第1欄「Lateral Limits」= 区域全体の外形座標
  col 30〜   … 第2欄。サブ区画 (1)(2) がある区域はここに区画ごとの座標と上下限
  文章定義   … 円/扇形/円環は座標が並ばず英文で書かれる。定型文を正規表現で拾い、
               それでも無理なものだけ SPEC に手書きする(R-130・R-521)。
  上下限・使用時間・種別は列位置がページごとにずれるので、**列で切らず
  レコード全文から既知の語で拾う**(by NOTAM / Continuous / DLY / MON-FRI …)。

出力: res.json {"eff":..,"f":[{n,jp,k,up,lo,hr,res,rmk,pts},..]}
  k  … 'R'=制限空域 / 'W'=警戒区域 / 'RJR'=航空法80条の飛行制限区域
  pts… [[lat,lng],..] または リングの配列(円環のW-183Aは外周+穴)
使い方: python3 tools/gen_res.py
"""
import re, os, sys, glob, json, math, subprocess

CO = re.compile(r'(\d{6}(?:\.\d+)?)N\s*/?\s*(\d{7}(?:\.\d+)?)E')
JPC = re.compile(r'[ぁ-んァ-ヶ一-龥]')
SKIP = re.compile(r'AIP Japan|Civil Aviation Bureau|AIRSPACE RESTRICTIONS|RESTRICTED AREAS'
                  r'|DANGER AREAS|ENR 5\.1|^\s*(Name|Lateral Limits|Upper|Lower|Identification)')
# 区域名は「R-123…/W-45…」か「全部大文字の語の並び」だけ。
# こうしないと "A circle radius of 5nm centered at" のような文章の続きを
# 新しい区域と誤認する(実際に3件誤検出した)
NAME = re.compile(r'^((?:[RW]-\d+[A-Z]?\b[A-Za-z0-9\-/\' ]*?)|(?:[A-Z][A-Z0-9\-/]*(?: [A-Z][A-Z0-9\-/]*)*))(?:\s{2,}|\s*$)')

NM_M, SM_M, KM_M = 1852.0, 1609.344, 1000.0

def dms(la, lo):
    return (round(int(la[0:2]) + int(la[2:4])/60 + float(la[4:])/3600, 6),
            round(int(lo[0:3]) + int(lo[3:5])/60 + float(lo[5:])/3600, 6))

def circle(lat, lng, rad_m, a0=0.0, a1=360.0, n=None):
    """真方位 a0→a1 の弧上の点列。扇形・半円にも使う"""
    n = n or max(12, int(abs(a1 - a0) / 4))
    k = math.cos(math.radians(lat))
    out = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        d = rad_m / 111320.0
        out.append([round(lat + d*math.cos(a), 6), round(lng + d*math.sin(a)/k, 6)])
    return out

def dest(lat, lng, brg, dist_m):
    k = math.cos(math.radians(lat)); d = dist_m / 111320.0
    a = math.radians(brg)
    return [round(lat + d*math.cos(a), 6), round(lng + d*math.sin(a)/k, 6)]

# ── 文章でしか書かれておらず、定型文にも当てはまらない区域 ──────────────
def spec_r130():
    """陸上=基点から半径1哩の半円、海上=北界058°T/南界108°T/東界は半径5smの弧。
       半円は陸側(西)。北端・南端から方位線を引いて5smの弧で閉じる"""
    la, lo = dms('405208.6', '1412302.1')
    land = circle(la, lo, 1*SM_M, 180, 360)          # 西半分(S→W→N)
    ntip, stip = dest(la, lo, 0, 1*SM_M), dest(la, lo, 180, 1*SM_M)
    n58 = dest(ntip[0], ntip[1], 58, 5*SM_M)
    s108 = dest(stip[0], stip[1], 108, 5*SM_M)
    arc = circle(la, lo, 5*SM_M, 58, 108)
    return land + [n58] + arc + [s108]

def spec_r521(km):
    """基点から半径km、真方位043°〜133°の扇形"""
    la, lo = dms('410403', '1412312')
    return [[la, lo]] + circle(la, lo, km*KM_M, 43, 133) + [[la, lo]]

SPEC = {
 'R-130 MISAWA':   [dict(pts=spec_r130(),
                    rmk='陸上=基点から半径1哩の半円、海上=北界058°T・南界108°T・東界は半径5smの弧')],
 'R-521 ROKKASHO': [dict(pts=spec_r521(20), sfx=' (20km扇形)'),
                    dict(pts=spec_r521(10), sfx=' (10km扇形)')],
}

def latest():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/ENR_*.pdf',
                '~/Downloads/1_AIP (PDF)/*/ENR_*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: return f[-1]
    return None

def cut(t, a, b):
    i = t.index(a); j = t.index(b, i)
    return t[i:j]

def limits(seg):
    """『上限 / ------- / 下限』の3行組。
       ⚠ 列位置がページごとにずれるので罫線行を基準にするが、**同じ列帯だけ**を
         見ること。行全体を見ると備考欄の電話番号(TEL 080-…)を下限80ftと誤読する"""
    V = re.compile(r'\b(UNL|SFC|GND|FL\d{2,3}|\d{3,5})\b')
    for i, s in enumerate(seg):
        r = re.search(r'-{6,}', s)
        if not r: continue
        a, b = max(0, r.start() - 14), r.end() + 14
        up = dn = None
        for j in range(i-1, max(-1, i-4), -1):
            m = V.search(seg[j][a:b])
            if m: up = m.group(1); break
        for j in range(i+1, min(len(seg), i+4)):
            m = V.search(seg[j][a:b])
            if m: dn = m.group(1); break
        if up and dn: return up, dn
    return None, None

def ft(v):
    if v in (None, 'UNL'): return None
    if v in ('SFC', 'GND'): return 0
    if v.startswith('FL'): return int(v[2:]) * 100
    return int(v)

def from_prose(seg):
    """円・円環・海岸から◯nm の定型文。これで大半の島嶼区域が拾える"""
    txt = ' '.join(s[:60].strip() for s in seg)
    txt = re.sub(r'\s+', ' ', txt)
    U = {'nm': NM_M, 'sm': SM_M, 'km': KM_M, 'm': 1.0}
    m = re.search(r'beyond\s+(\d+(?:\.\d+)?)\s*(nm|sm|km|m)\s+to\s+(\d+(?:\.\d+)?)\s*(nm|sm|km|m)'
                  r'\s+radius of[^.]*?(\d{6}(?:\.\d+)?)N\s*/?\s*(\d{7}(?:\.\d+)?)E', txt)
    if m:                                     # 円環(内側に穴)
        la, lo = dms(m.group(5), m.group(6))
        out = circle(la, lo, float(m.group(3))*U[m.group(4)])
        inn = circle(la, lo, float(m.group(1))*U[m.group(2)])
        return [out, inn], f'内側{m.group(1)}{m.group(2)}を除く円環'
    m = re.search(r'radius of\s+(\d+(?:\.\d+)?)\s*(nm|sm|km|m)[^.]*?centered at\s*'
                  r'(\d{6}(?:\.\d+)?)N\s*/?\s*(\d{7}(?:\.\d+)?)E', txt) \
        or re.search(r'circle\s+radius of\s+(\d+(?:\.\d+)?)\s*(nm|sm|km|m)\s+centered at\s*'
                     r'(\d{6}(?:\.\d+)?)N\s*/?\s*(\d{7}(?:\.\d+)?)E', txt)
    if m:
        la, lo = dms(m.group(3), m.group(4))
        return circle(la, lo, float(m.group(1))*U[m.group(2)]), None
    m = re.search(r'(\d{6}(?:\.\d+)?)N\s*/?\s*(\d{7}(?:\.\d+)?)E\s+and ocean area\s+'
                  r'extending\s+(\d+(?:\.\d+)?)\s*(nm|sm|km)', txt)
    if m:                                     # 島+海岸から◯nm。島の輪郭は無いので円で近似
        la, lo = dms(m.group(1), m.group(2))
        return circle(la, lo, float(m.group(3))*U[m.group(4)]), \
               '島の海岸線から' + m.group(3) + m.group(4) + '(円で近似)'
    return None, None

SUBMK = re.compile(r'\(([1-9])\)')

def sub_areas(seg):
    """第2欄の (1)(2)(3) 区画。区画ごとに上下限と座標を持つ。
       ⚠ 最初の (1) は**区域名と同じ行**に出る(R-116/R-121)。行末ではなく
         その右に備考欄が続くので、行末で探すと必ず外れる。**列位置で見ること**。
       ⚠ 列を60までに絞るのは、備考欄の連絡先一覧「(1)DIALECT (2)NYUTA TWR」を
         区画と誤認しないため(列100付近に出る)"""
    marks = []
    for i, s in enumerate(seg):
        for m in SUBMK.finditer(s):
            if 24 <= m.start() < 62: marks.append((i, m.group(1))); break
    out = []
    for k, (i, mk) in enumerate(marks):
        blk = seg[i:(marks[k+1][0] if k+1 < len(marks) else len(seg))]
        up, dn = limits(blk)
        pts = [dms(m.group(1), m.group(2)) for s in blk for m in CO.finditer(s)
               if m.start() >= 30]
        if len(pts) >= 3 and up and dn: out.append((mk, up, dn, pts))
    return out


def parse_rjr(t):
    """ENR 5.1.2。RJR1〜3。円形で、RJR1だけ経線で西側に切られる"""
    seg = cut(t, '2. 飛行制限区域', '3. 危険区域').split('\n')
    out, idx = [], [i for i, s in enumerate(seg) if re.match(r'\s*RJR\d', s)]
    for k, i in enumerate(idx):
        rec = [s for s in seg[i:(idx[k+1] if k+1 < len(idx) else len(seg))] if not SKIP.search(s)]
        txt = re.sub(r'\s+', ' ', ' '.join(rec))
        nm = re.match(r'\s*(RJR\d)', rec[0]).group(1)
        # 半径と中心は別々に拾う。1本の正規表現でつなぐと、間に入る
        # 「(6km)」「HR of flight restriction:H24」等の数字で必ず外れる
        mr = re.search(r'radius of\s+([\d.]+)\s*(NM|nm|km)', txt)
        mc = re.search(r'(\d{6})N\s*/?\s*(\d{7})E', txt)
        if not (mr and mc): continue
        rad = float(mr.group(1)) * (NM_M if mr.group(2).lower() == 'nm' else KM_M)
        la, lo = dms(mc.group(1), mc.group(2))
        pts = circle(la, lo, rad)
        # 円をさらに経線/緯線で半分に切るものがある(RJR1=西側 / RJR3=北側)
        rmk = ''
        w = re.search(r'(west|east) side area of\s*(\d{7})E', txt)
        if w:
            c = int(w.group(2)[0:3]) + int(w.group(2)[3:5])/60 + int(w.group(2)[5:7])/3600
            pts = [q for q in pts if (q[1] <= c if w.group(1) == 'west' else q[1] >= c)]
            rmk = w.group(2) + 'E の線の' + ('西' if w.group(1) == 'west' else '東') + '側のみ'
        w = re.search(r'(north|south) side area of\s*(\d{6})N', txt)
        if w:
            c = int(w.group(2)[0:2]) + int(w.group(2)[2:4])/60 + int(w.group(2)[4:6])/3600
            pts = [q for q in pts if (q[0] >= c if w.group(1) == 'north' else q[0] <= c)]
            rmk = w.group(2) + 'N の線の' + ('北' if w.group(1) == 'north' else '南') + '側のみ'
        up, dn = limits(rec)
        # 見出しに区域名が出るので jp は使わず、代わりに調整先(Point of Contact)を出す。
        # 81条の2で飛行する場合は事前調整が要るので、ここが一番知りたい情報
        pc = re.search(r'Point of Contact:\s*(.+?)(?:\s{2,}|TEL|FAX|-{3,}|$)', txt)
        if pc:   # 段組を連結しているので上下限の欄(FL190/-----)が割り込む。落とす
            pcs = re.sub(r'\s*(?:FL\d{2,3}|UNL|SFC|GND|-{3,})\s*', ' ', pc.group(1))
            pcs = re.sub(r'\s+', ' ', pcs).strip()
        out.append(dict(n=nm, jp='', k='RJR', up=ft(up), lo=ft(dn),
                        res='航空法80条 飛行制限区域'
                            + (' / 調整先: ' + pcs if pc and pcs else ''),
                        hr=('H24' if 'H24' in txt else ''), rmk=rmk, pts=pts))
    return out

def parse_restrictions(t):
    L = t[t.index('4. 空域制限'):].split('\n')
    starts = []
    for i, ln in enumerate(L):
        if not ln[:1].strip() or SKIP.search(ln) or CO.match(ln.strip()): continue
        m = NAME.match(ln)
        if not m: continue
        nm = m.group(1).strip()
        if len(nm) < 3 or nm in ('Restricted Area', 'Warning Area'): continue
        starts.append((i, nm))
    out = []
    for k, (i, nm) in enumerate(starts):
        end = starts[k+1][0] if k+1 < len(starts) else len(L)
        seg = [s for s in L[i:end] if not SKIP.search(s)]
        # 和名。罫線(-----)や数値が同じ行に混ざるので日本語部分だけ取る
        jp = ''
        # ⚠ 窓は広めに取ること。R-130は英文の区域定義が先に来るので和名が13行下
        for s2 in seg[1:20]:
            if not JPC.search(s2[:26]): continue
            c = re.sub(r'\s+', '', re.sub(r'[-\d]+$', '', s2[:26].strip()))
            if not c or '区域は' in c or c[0].isdigit(): continue  # 英文定義の和訳は名前ではない
            jp = c; break
        c1, c2 = [], []
        for s in seg:
            for m in CO.finditer(s):
                (c1 if m.start() < 30 else c2).append(dms(m.group(1), m.group(2)))
        up, dn = limits(seg)
        txt = ' '.join(seg)
        hr = ''
        for pat in (r'by NOTAM', r'by AIP SUP', r'[Cc]ontinuous', r'MON-FRI', r'MON-SAT', r'\bDLY\b'):
            if re.search(pat, txt): hr = re.search(pat, txt).group(0); break
        tm = re.search(r'\b(\d{4})\s*-\s*(\d{4})\b', txt)
        if tm: hr = (hr + ' ' + tm.group(0)).strip()
        if 'VMC-IMC' in txt: hr = (hr + ' VMC-IMC').strip()
        # 種別(第3欄)。「(USN surface and anti-aircraft firing)」のように
        # 1つの括弧が3行に折り返すので、**第3欄の列帯を切り出して縦に連結**する。
        # 連結後の全文に正規表現をかけると、隣の欄を巻き込むか途中で切れる
        # 種別(第3欄)。「(USN surface and anti-aircraft firing)」のように
        # 1つの括弧が3行に折り返すので、**第3欄の列帯を切り出して縦に連結**する。
        # 連結後の全文に正規表現をかけると、隣の欄を巻き込むか途中で切れる。
        # ⚠ 見出し語が無く括弧書きだけの区域もある(W-178/W-179)。その場合は
        #   「(USAF …」の出現位置を帯の基準にする
        res = ''
        AN = re.compile(r'(Restricted|Warning) Area|\((?:USN|USAF|USA|USMC|US MARINES|JSDF-[GAM])\b')
        cm = next((AN.search(x) for x in seg if AN.search(x)), None)
        if cm:
            a = max(0, cm.start() - 2)
            # 各行は**空白3つ以上で次の欄(使用時間)に移る**ので、そこで切る
            band = [re.split(r'\s{3,}', x[a:a+40].strip())[0] for x in seg]
            res = re.sub(r'\s+', ' ', ' '.join(b for b in band
                          if b and re.fullmatch(r"[ -~]+", b))).strip()
            # ⚠ 最後の ) で切ると、備考欄の連絡先「(Hyakuri Tel …」まで残る。
            #   **最初の ( に対応する ) で切る**
            i0 = res.find('(')
            if i0 >= 0 and ')' in res[i0:]: res = res[:res.index(')', i0)+1]
        rec = dict(n=nm, jp=jp, k=('W' if nm.startswith('W-') else 'R'),
                   up=ft(up), lo=ft(dn), hr=hr, res=res, rmk='')
        if nm in SPEC:
            for s in SPEC[nm]:
                r = dict(rec); r['n'] = nm + s.get('sfx', ''); r['pts'] = s['pts']
                r['rmk'] = s.get('rmk', '')
                out.append(r)
            continue
        subs = sub_areas(seg)
        if len(subs) >= 2:
            # R-116/R-121 は上限の違う副区画に分かれる。全体の外形(第1欄)ではなく
            # **副区画ごとに1つの区域として出す**。合わせると全体になる。
            # ここを外形1枚で描くと、R-116の北西部(12000ft)まで UNL 扱いになってしまう
            for si, (mk, up2, dn2, pts2) in enumerate(subs, 1):
                r = dict(rec)
                r['n'] = nm + ' (' + mk + ')'
                r['up'], r['lo'] = ft(up2), ft(dn2)
                r['pts'] = [[a, b] for a, b in pts2]
                out.append(r)
            continue
        if len(c1) >= 3:
            rec['pts'] = [[a, b] for a, b in c1]
        else:
            pts, note = from_prose(seg)
            if not pts:
                print(f'  ⚠ 形状を起こせない: {nm}', file=sys.stderr); continue
            rec['pts'] = pts
            if note: rec['rmk'] = note
        if 'Excluding' in txt:
            ex = re.search(r'Excluding ([A-Za-z0-9\- ]+?)(?:\s{2,}|$)', txt)
            if ex: rec['rmk'] = (rec['rmk'] + ' ' + ex.group(0).strip()).strip()
        out.append(rec)
    return out

def main():
    pdf = latest()
    if not pdf: print('AIPのENR PDFが見つかりません', file=sys.stderr); sys.exit(1)
    t = subprocess.run(['pdftotext', '-layout', pdf, '-'],
                       capture_output=True, text=True).stdout
    # 目次にも同じ見出しが出るので、**本文にしか無い英文見出し**で切る
    t = cut(t, 'PROHIBITED, RESTRICTED AND', 'ENR 5.2 EXERCISE AND TRAINING AREAS')
    f = parse_rjr(t) + parse_restrictions(t)
    eff = os.path.basename(os.path.dirname(pdf))
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'res.json')
    json.dump({'eff': eff, 'src': 'AIP Japan ENR 5.1', 'f': f},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    import collections
    print(f'{len(f)} 区域 → res.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')
    print('  種別:', dict(collections.Counter(x['k'] for x in f)))
    print('  上限あり:', sum(1 for x in f if x['up'] is not None),
          '/ 使用時間あり:', sum(1 for x in f if x['hr']))
    for x in f[:6]:
        print(f"   {x['n']:24}{x['jp'][:12]:14}{str(x['lo'])+'-'+str(x['up'] or 'UNL'):14}{x['hr']}")

if __name__ == '__main__': main()
