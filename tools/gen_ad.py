#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飛行場マスタ 生成 (ad.json)
============================
出典: AIP各飛行場の **AD 2.2 / AD 3.2**(ARP座標・標高)、**AD 2.12 / AD 3.12**(滑走路)、
      **AD 2.3 / AD 3.3**(運用時間)、**AD 2.20〜2.22**(場周経路・回転翼機の方式)

これまで飛行場レイヤーは「管制圏・情報圏を持つ飛行場」だけだった。
そのため**圏を持たない飛行場が丸ごと欠けていた**(佐渡・但馬・奥尻・大館能代・
大村・粟国・慶良間・小松島など約20)。AD2/AD3のあるもの(127+6=133)を全部拾う。

  ⚠ AIPにAD2/AD3のページが無い飛行場は当然ここには入らない。
    GEN 2.4(位置指示記号)にだけ載る滝ヶ原RJATなどは `EXTRA` で座標を直書きする。

出力: ad.json {"eff":..,"f":[{icao,n,en,lat,lng,elev,rwy,vfr,hr,tp,heli},...]}
  hr=ATSの運用時間(UTC) tp=場周経路の記述 heli=回転翼機の方式(抜粋)

  ⚠ **場周経路は本文に書いてある飛行場が少ない**(高度を明記しているのは7空港のみ)。
    大半は AD 2.24 の**チャートにしか無い**ので、本文が取れないものは
    「チャート参照」とだけ出す。抜粋は要約ではなく原文の一部なので、
    アプリ側でも必ず原文確認を促すこと。
使い方: python3 tools/gen_ad.py
AIRAC更新のたびに再実行して件数の差分を見る。
"""
import re, os, sys, glob, json, subprocess

# AIPにページが無いが載せたい飛行場。座標は国土地理院のジオコーダ/地形図から。
# 滝ヶ原はGEN 2.4に位置指示記号だけがあり、AD 1.3にも載っていない
EXTRA = [
    dict(icao='RJAT', n='滝ヶ原', en='Takigahara', lat=35.31611, lng=138.88083,
         src='陸自滝ヶ原駐屯地(OSM)'),
]

def gen24_names(base):
    """GEN 2.4(位置指示記号)の「和名 CODE 英名 CODE」表から和名を拾う。
       AD2/AD3は英名しか持たないので、ここが唯一のまとまった和名源"""
    f = glob.glob(os.path.join(base, 'GEN_*.pdf'))
    if not f: return {}
    t = subprocess.run(['pdftotext', '-layout', f[0], '-'],
                       capture_output=True, text=True).stdout
    m = {}
    for ln in t.split('\n'):
        g = re.match(r'\s*(\S.*?)\s{2,}(R[JO][A-Z]{2})\s{2,}(.+?)\s{2,}(R[JO][A-Z]{2})\s*$', ln)
        if g and g.group(2) == g.group(4):
            m[g.group(2)] = re.sub(r'\s+', '', g.group(1))
    return m


# 和名。AD2は英名しか持たないので、既存の対応表を再利用する
def jp_names():
    here = os.path.dirname(os.path.abspath(__file__))
    m = {}
    try:
        for x in json.load(open(os.path.join(here, 'natl_ctr.json'))):
            m[x['icao']] = x['n']
    except Exception:
        pass
    try:
        for x in json.load(open(os.path.join(here, 'metar_stations.json'))):
            m.setdefault(x['icao'], x['n'])
    except Exception:
        pass
    return m


def dms(la, lo):
    return (round(int(la[0:2]) + int(la[2:4])/60 + float(la[4:-1])/3600, 5),
            round(int(lo[0:3]) + int(lo[3:5])/60 + float(lo[5:-1])/3600, 5))


def latest_dir():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*',
                '~/Downloads/1_AIP (PDF)/*'):
        d = sorted(glob.glob(os.path.expanduser(pat)))
        d = [x for x in d if os.path.isdir(os.path.join(x, 'AD2_Combine'))]
        if d: return d[-1]
    return None


def parse(pdf, sec):
    """secは 2(AD2) か 3(AD3)。ARP・標高・滑走路・交通種別を拾う"""
    t = subprocess.run(['pdftotext', '-layout', pdf, '-'],
                       capture_output=True, text=True).stdout
    icao = os.path.basename(pdf).split('__')[0]
    r = {'icao': icao}
    m = re.search(re.escape(icao) + r'\s*[-—–]\s*([A-Z][A-Za-z0-9 /\'\-\.]+)', t)
    if m: r['en'] = ' '.join(m.group(1).split())[:32]
    # 区切りは空白のことも「/」のこともあり、普天間のように
    # 「2616N/12745E, 261614.50N/1274452.97E*」と粗い値が先に来る場合もある。
    # 秒まである長い方を優先して拾う
    # ヘリポートは「Heliport reference point coordinates」、鳥取のように
    # 見出しと座標が別行に分かれるものもあるので後ろ3行まで見る
    # 見出しが「Heliport reference point / coordinates…」と折り返したり、
    # 鳥取のように座標が見出しの1行**上**に来ることもある。前後を見る
    seg = None
    mh = re.search(r'(?:ARP coordinates|Heliport reference point)', t)
    if mh:
        ls = t[:mh.start()].split('\n')
        seg = '\n'.join(ls[-2:]) + t[mh.start():mh.start() + 400]
    m = None
    if seg:
        cand = re.findall(r'(\d{6}(?:\.\d+)?)N\s*/?\s*(\d{7}(?:\.\d+)?)E', seg)
        if cand: m = max(cand, key=lambda c: len(c[0]) + len(c[1]))
    if not m: return None
    r['lat'], r['lng'] = dms(m[0] + 'N', m[1] + 'E')
    # 「Elevation/ Reference\n temperature   135ft」のように見出しが折り返す
    m = re.search(r'Elevation\s*/\s*Reference[\s\S]{0,40}?(-?\d+(?:\.\d+)?)\s*ft', t, re.I)
    if m: r['elev'] = int(float(m.group(1)))
    m = re.search(r'Types of traffic permitted[^\n]*\n?[^\n]*?((?:IFR|VFR)[\-/ ]*(?:VFR)?)', t)
    if m: r['vfr'] = m.group(1).strip()
    # 運用時間: AD 2.3 の ATS 行(無ければ AD Administration)。
    # 「2330 - 0800 / Other time 1HR PN」のように次行に補足が続くことがある
    sec3 = re.search(r'AD %s\.3 OPERATIONAL HOURS(.*?)(?:AD %s\.4|$)' % (sec, sec), t, re.S)
    if sec3:
        for lbl in (r'ATS(?!\s*Reporting)', r'AD Administration'):
            mm = re.search(lbl + r'\s{2,}(.+?)(?:\n\s*\n|\n\s*\d+\s{2,})', sec3.group(1), re.S)
            if mm:
                v = ' / '.join(x.strip() for x in mm.group(1).split('\n') if x.strip())
                v = re.sub(r'\s{2,}', ' ', v)[:110]
                if v and v.lower() != 'nil': r['hr'] = v; break

    # 場周経路: AD 2.20〜2.22 の英文側だけを拾う(和英2段組なのでASCII列を取る)
    sec20 = re.search(r'AD %s\.20 (.*?)(?:AD %s\.23|$)' % (sec, sec), t, re.S)
    if sec20:
        body = sec20.group(1)
        def en_of(ln):    # 和英2段組なので、行からASCIIのまとまりだけ取る
            return ' '.join(re.findall(r'[ -~]{12,}', ln)).strip()
        tp = [en_of(l) for l in body.split('\n') if re.search(r'[Tt]raffic pattern', en_of(l))]
        if tp: r['tp'] = ' '.join(tp)[:300]
        # 回転翼機の方式は「(ROTOR CRAFT)」等の見出しがある場合だけ。
        # 「4. Parking area for helicopters」のような節見出しを拾わないよう、
        # 括弧付きの見出しに限定し、次の括弧見出し/節番号までを本文とする
        mh = re.search(r'[(（]\s*(?:ROTOR ?CRAFT|HELICOPTERS?)\s*[)）]', body, re.I)
        if mh:
            tail = body[mh.end():]
            stop = re.search(r'\n\s*\d+\.\s|[(（]\s*FIXED', tail)
            tail = tail[:stop.start()] if stop else tail[:2500]
            hl = [en_of(l) for l in tail.split('\n')]
            hl = [x for x in hl if len(x) > 20 and not re.search(r'Civil Aviation Bureau|AIP Japan', x)]
            if hl: r['heli'] = ' '.join(hl)[:300]

    # 滑走路: AD 2.12 の「番号 / 真方位 / 寸法」から「10/28 890×25」の形に
    sec12 = re.search(r'AD %s\.12 RUNWAY PHYSICAL CHARACTERISTICS(.*?)(?:AD %s\.13|$)'
                      % (sec, sec), t, re.S)
    if sec12:
        rw = re.findall(r'^\s{2,}(\d{2}[LRC]?|H\d?)\s+\d{3}\.\d+°\s+([\d,]+\s*[×xX]\s*[\d,]+)',
                        sec12.group(1), re.M)
        if rw:
            dim = rw[0][1].replace(' ', '')
            r['rwy'] = '/'.join(x[0] for x in rw) + ' ' + dim
    return r


def main():
    base = latest_dir()
    if not base:
        print('AIPのフォルダが見つかりません', file=sys.stderr); sys.exit(1)
    jp = jp_names()
    for k, v in gen24_names(base).items(): jp.setdefault(k, v)
    out, seen = [], set()
    for sec, sub in ((2, 'AD2_Combine'), (3, 'AD3')):
        for pdf in sorted(glob.glob(os.path.join(base, sub, '*.pdf'))):
            r = parse(pdf, sec)
            if not r or r['icao'] in seen: continue
            seen.add(r['icao'])
            r['n'] = jp.get(r['icao'], r.get('en', r['icao']))
            out.append(r)
    for x in EXTRA:
        if x['icao'] not in seen: out.append(x); seen.add(x['icao'])
    out.sort(key=lambda x: x['icao'])

    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'ad.json')
    eff = os.path.basename(base)
    json.dump({'eff': eff, 'src': 'AIP Japan AD 2.2/2.12', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 飛行場 → ad.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')
    print('  標高あり:', sum(1 for x in out if 'elev' in x),
          '/ 滑走路あり:', sum(1 for x in out if 'rwy' in x),
          '/ 運用時間あり:', sum(1 for x in out if 'hr' in x),
          '/ 場周経路あり:', sum(1 for x in out if 'tp' in x),
          '/ 回転翼記述あり:', sum(1 for x in out if 'heli' in x))
    miss = [x['icao'] for x in out if 'elev' not in x]
    if miss: print('  標高が読めない:', ' '.join(miss))


if __name__ == '__main__': main()
