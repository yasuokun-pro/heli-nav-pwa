#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
臨時空域(SUP)生成 (sup.json)
=============================
AIS「3_SUP(KML)」のKMLから臨時空域(射撃訓練・臨時訓練空域・無人機運用・
ロケット打上げ等)のポリゴンと、期間・高度・備考を抽出する。

出力: sup.json {"updated":"YYYY-MM-DD","s":[{n,subj,period,alt,rmk,pts:[[lat,lng],..]},..]}
使い方: python3 tools/gen_sup.py
AIRAC更新時: 3_SUP(KML) を新しいものに差し替えて再実行。
※SUPは有効期限があるため、期限切れのものは表示側で判別できるよう period を保持する。
"""
import re, os, glob, json, sys, datetime, html as htmlmod

SRC = os.path.expanduser('~/Downloads/AIP File Download Service/3_SUP(KML)')

def field(h, key):
    """英語SUP形式: <td>Period</td><td>値</td>"""
    m = re.search(r'<td>' + key + r'[^<]*</td>\s*<td>(.*?)</td>', h, re.S)
    if not m: return ''
    v = re.sub(r'<br\s*/?>', ' ', m.group(1))
    return htmlmod.unescape(re.sub(r'<[^>]+>', '', v)).strip()

def jfield(h, key):
    """ドローンKML形式: <td>終了日：値</td> (1セル内に全角コロン区切り)"""
    m = re.search(r'<td>\s*' + key + r'[^：:]*[：:](.*?)</td>', h, re.S)
    if not m: return ''
    v = re.sub(r'<br\s*/?>', ' ', m.group(1))
    return htmlmod.unescape(re.sub(r'<[^>]+>', '', v)).strip()

def main():
    files = sorted(glob.glob(SRC + '/**/*.kml', recursive=True))
    if not files:
        print('SUP KML が見つかりません:', SRC, file=sys.stderr); sys.exit(1)
    out = []
    for fp in files:
        cat = os.path.basename(os.path.dirname(fp))
        doc = open(fp, encoding='utf8', errors='ignore').read()
        for pm in re.finditer(r'<Placemark>(.*?)</Placemark>', doc, re.S):
            b = pm.group(1)
            nm = re.search(r'<name>(.*?)</name>', b, re.S)
            name = htmlmod.unescape(nm.group(1).strip()) if nm else ''
            desc = b
            subj = field(desc, 'Subject')
            if subj:   # 英語のSUP KML(射撃訓練・臨時訓練空域など)
                rec = dict(n=name, cat=cat, subj=subj,
                           id=field(desc, 'Name／ID') or field(desc, 'Name/ID'),
                           period=field(desc, 'Period'), alt=field(desc, 'Altitude'),
                           rmk=field(desc, 'Remarks'))
            else:      # 日本語のドローン飛行禁止空域KML(1セル内に「項目：値」)
                end  = jfield(desc, '終了日')
                hrs  = jfield(desc, '時間帯')
                addr = jfield(desc, '住所等')
                num  = jfield(desc, '最大機数')
                kind = jfield(desc, '種類')
                notam= jfield(desc, '備考')
                if end:
                    e = re.sub(r'^(\d{4})(\d{2})(\d{2})$', r'\1/\2/\3', end.strip())
                    period = f'{e}まで' + (f' / 時間帯(UTC): {hrs}' if hrs else '')
                else:
                    period = (f'時間帯(UTC): {hrs}' if hrs else '')
                rmk = ' / '.join(x for x in [
                    addr, (f'最大{num}機' if num else ''),
                    (kind.replace('\n', ' ') if kind else ''),
                    (f'NOTAM {notam}' if notam else '')] if x)
                rec = dict(n=name, cat=cat, subj='無人航空機 飛行区域(ドローン)',
                           id='', period=period, alt=jfield(desc, '最大高度'), rmk=rmk)
            for co in re.finditer(r'<coordinates>(.*?)</coordinates>', b, re.S):
                pts = []
                for tok in co.group(1).split():
                    p = tok.split(',')
                    if len(p) >= 2:
                        try: pts.append([round(float(p[1]), 5), round(float(p[0]), 5)])
                        except ValueError: pass
                if len(pts) >= 3:
                    r = dict(rec); r['pts'] = pts; out.append(r)
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'sup.json')
    json.dump({'updated': datetime.date.today().isoformat(), 's': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 臨時空域 → sup.json ({os.path.getsize(dst)/1024:.0f}KB)')
    from collections import Counter
    print('種別:', Counter(x['subj'] or x['cat'] for x in out).most_common(8))

if __name__ == '__main__': main()
