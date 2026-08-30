#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全国(関東以外)のCTR/情報圏の基礎データ抽出 → tools/natl_ctr.json
================================================================
各飛行場 AD2 の AD 2.17 から ARP・半径・上限・種別・名称を取り出す。
ここでは「円+上限」までを作り、分割/除外のある空域は gen_asp.py の
OVERRIDE で正確な形状に補正する(natl_ctr.json は素材データ)。

使い方: python3 tools/gen_natl_ctr.py   → natl_ctr.json を更新
その後  python3 tools/gen_asp.py --splice で index.html に反映。
"""
import re, glob, os, json, subprocess, sys

A = os.path.expanduser('~/Downloads/1_AIP (PDF)')
KANTO = {'RJTT','RJAA','RJAH','RJTA','RJTC','RJTJ','RJTY','RJTK','RJTL','RJTE','RJTU','RJTO'}
# ICAO→和名(AD2から機械抽出できないものを補う)
JP = {'RJNS':'静岡','RJNY':'静浜','RJSU':'霞目','RJFZ':'築城','RJFA':'芦屋','RJNG':'岐阜',
      'RJOB':'岡山','RJSI':'花巻','RJCA':'旭川(陸)','RJCJ':'千歳','RJAK':'霞ヶ浦',
      'RJKB':'沖永良部','RJKN':'徳之島','RJNF':'福井','RJST':'松島','RJSH':'八戸',
      'RJSM':'三沢','RJDC':'山口宇部','RJEB':'紋別','RJER':'利尻','RJTQ':'三宅島',
      'RJTH':'八丈島','RJCN':'中標津','RJCW':'稚内','RJDM':'目達原','RJNO':'隠岐',
      'RJOE':'明野','RJOF':'防府','RJSY':'庄内','RJAN':'新島(空)','RJAZ':'神津島',
      'ROMD':'南大東','RORK':'北大東','RORS':'下地島','ROYN':'与那国','RJFY':'鹿屋','RORY':'与論','RJSR':'大館能代','RJCK':'釧路','RJSC':'山形',
      'RJAF':'松本','RJBD':'南紀白浜','RJOR':'鳥取'}

def dms(s):
    m = re.match(r'(\d{2,3})(\d{2})(\d{2}(?:\.\d+)?)', s)
    return float(m.group(1)) + float(m.group(2))/60 + float(m.group(3))/3600

def latest_dir():
    ds = sorted(glob.glob(A + '/*/AD2_Combine'))
    return ds[-1] if ds else None

def main():
    d = latest_dir()
    if not d: print('AD2_Combine が見つかりません', file=sys.stderr); sys.exit(1)
    here = os.path.dirname(os.path.abspath(__file__))
    # ⚠ 和名は **今の natl_ctr.json を土台にする**。index.htmlのASP[]は
    #   AIP形状に置き換わった飛行場を落としてあるので、そこだけ見ると
    #   硫黄島→Iwoto のように和名が英名に戻ってしまう
    names = {}
    prev = os.path.join(here, 'natl_ctr.json')
    if os.path.exists(prev):
        for x in json.load(open(prev)):
            if re.search(r'[^\x00-\x7F]', x.get('n', '')): names[x['icao']] = x['n']
    idx = os.path.join(here, '..', 'index.html')
    if os.path.exists(idx):  # 既存ASP[]の和名を流用
        h = open(idx).read()
        m = re.search(r'const ASP=\[(.*?)\n\];', h, re.S)
        if m:
            for mm in re.finditer(r"n:'([^']+)',icao:'([A-Z]{4})'", m.group(1)):
                names[mm.group(2)] = mm.group(1)
    rows = []
    for pdf in sorted(glob.glob(d + '/*.pdf')):
        icao = os.path.basename(pdf).split('__')[0]
        if icao in KANTO: continue
        txt = subprocess.run(['pdftotext','-layout',pdf,'-'], capture_output=True, text=True).stdout
        # ⚠ **座標が "ARP coordinates" より前に出る版がある**(右列が先に flush される。
        #   鳥取RJORで実際に起きた)。前後どちらも見る
        i = txt.find('ARP coordinates')
        marp = (re.search(r'(\d{6}(?:\.\d+)?)N[ /]*(\d{7}(?:\.\d+)?)E', txt[i:i+400])
                if i >= 0 else None) or (
               re.search(r'(\d{6}(?:\.\d+)?)N[ /]*(\d{7}(?:\.\d+)?)E', txt[max(0,i-300):i])
                if i >= 0 else None)
        if not marp: continue
        arp = (round(dms(marp.group(1)),5), round(dms(marp.group(2)),5))
        s17 = re.search(r'AD 2\.17 ATS AIRSPACE(.*?)AD 2\.1[89]', txt, re.S)
        if not s17: continue
        seg = s17.group(1)
        if re.search(r'\bNil\b', seg[:250]): continue
        # ⚠ **"9km(5NM)" と km が先に来る版がある**(釧路・山形・松本・南紀白浜)。
        #   nm を先に探すだけだと丸ごと取りこぼす
        mr = (re.search(r'radius of\s+([\d.]+)\s*nm\s*(?:\([\d.]+\s*km\))?\s+of\s+(?:New\s+)?([A-Za-z][A-Za-z\-]+)\s+ARP', seg, re.I)
              or re.search(r'radius of\s+[\d.]+\s*km\s*\(\s*([\d.]+)\s*nm\s*\)', seg, re.I)
              or re.search(r'radius of\s+([\d.]+)\s*nm', seg, re.I))
        if not mr: continue
        r_nm = float(mr.group(1))
        en = mr.group(2).title() if (mr.lastindex or 0) >= 2 else icao
        # 上限ft
        # 上限ft: 列が分断されるため "N or"(=or below) を優先。
        # 運用時間(1315-2245)や座標を拾わないよう時刻レンジは除外する。
        up = 0
        seg_nt = re.sub(r'\b\d{4}\s*-\s*\d{4}\b', ' ', seg)   # 時刻レンジを除去
        num = lambda s: int(re.sub(r'[, ]', '', s))
        # "3 000 or below" のように数字内に空白が入る表記があるので許容する
        for pat in (r'(\d[\d, ]{2,6}\d)\s*or\b', r'Below\s*(\d[\d, ]{2,5}\d)',
                    r'(?:including|to but not including)\s*(\d[\d, ]{2,5}\d)'):
            m = re.search(pat, seg_nt, re.I)
            if m and 200 <= num(m.group(1)) <= 20000: up = num(m.group(1)); break
        if not up:
            body = seg_nt[seg_nt.find('(ft)')+4:] if '(ft)' in seg_nt else seg_nt
            for m in re.finditer(r'\b([\d,]{3,6})\b', body):
                n = int(m.group(1).replace(',',''))
                if 200 <= n <= 20000: up = n; break
        # 種別: 列レイアウトで語が分断されるため、コールサインで判定する。
        # TWR/Towerがあれば管制圏、無くてRadio/AFISなら情報圏。
        # ⚠ 呼出符号だけで見ると **"Yamagata radio" のような小文字表記を取りこぼして
        #   情報圏が管制圏になる**(山形・松本・南紀白浜・鳥取で実際に起きた)。
        #   名称の "Information zone" を最優先し、呼出符号は大小文字を無視する
        # ⚠ **TWRの判定を先に置くこと**。AD 2.17には隣接飛行場の情報圏が
        #   並記されることがあり、"Information zone" を先に見ると築城のような
        #   管制圏が情報圏に化ける
        if re.search(r'\bTWR\b|\bTower\b', seg, re.I): t = 'ctr'
        elif re.search(r'Information\s+zone', seg, re.I): t = 'inf'
        elif re.search(r'\bRadio\b|\bAFIS\b', seg, re.I): t = 'inf'
        else: t = 'ctr'
        rows.append(dict(icao=icao, n=JP.get(icao, names.get(icao, en)),
                         lat=arp[0], lng=arp[1], r_nm=r_nm, up=up, t=t))

    # AD3(ヘリポート様式)は AD2_Combine と別フォルダ・別書式(AD 3.16 ATS AIRSPACE)のため
    # 上のスキャン対象外。自衛隊ヘリポート6件中、空域を持つのはRJTS(相馬原)のみ確認済み
    # (2026-07-09時点。AIRAC更新時は AD3 フォルダの他5件も要目視確認)。
    rows.append(dict(icao='RJTS', n='相馬原', lat=36.43472, lng=138.95306,
                     r_nm=5.0, up=4000, t='ctr'))

    out = os.path.join(here, 'natl_ctr.json')
    json.dump(rows, open(out,'w'), ensure_ascii=False)
    print(f'{len(rows)} 件 → natl_ctr.json  (ctr={sum(1 for x in rows if x["t"]=="ctr")}, '
          f'inf={sum(1 for x in rows if x["t"]=="inf")}, 上限不明={sum(1 for x in rows if not x["up"])})')

if __name__ == '__main__': main()
