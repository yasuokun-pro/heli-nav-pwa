#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全国障害物データ生成 (obst.json)
=================================
AIS「4_OBSTACLE DATA / AREA1」のKML(都道府県別47ファイル)から
建物・風車・鉄塔などの障害物を抽出し、軽量JSONにまとめる。

出力: obst.json  {"updated":"YYYY-MM-DD","o":[[lat,lng,elevFt,heightFt,typeIdx,light],...]}
 - 座標は小数5桁、高さはftに換算して整数(容量削減のため配列形式)
 - typeIdx は TYPES の添字

使い方: python3 tools/gen_obst.py
AIRAC更新時: 新しい AREA1_*.kml.zip を展開して再実行。
"""
import re, os, glob, json, zipfile, sys, datetime, tempfile

SRC = os.path.expanduser('~/Downloads/AIP File Download Service/4_OBSTACLE DATA/1.AREA1')
TYPES = ['BUILDING','WINDMILL','TOWER','ANTENNA','CHIMNEY','POLE','CRANE','BRIDGE','MAST','OTHER']

def type_idx(t):
    t = (t or '').upper()
    for i, k in enumerate(TYPES):
        if k in t: return i
    return len(TYPES) - 1   # OTHER

def field(html, key):
    m = re.search(r'<td>' + key + r'</td>\s*<td>([^<]*)</td>', html)
    return (m.group(1).strip() if m else '')

def main():
    zips = sorted(glob.glob(SRC + '/*.kml.zip'))
    if not zips:
        print('AREA1 kml.zip が見つかりません:', SRC, file=sys.stderr); sys.exit(1)
    out = []
    with tempfile.TemporaryDirectory() as td:
        zipfile.ZipFile(zips[-1]).extractall(td)
        files = sorted(glob.glob(td + '/**/*.kml', recursive=True))
        for fp in files:
            doc = open(fp, encoding='utf8', errors='ignore').read()
            for pm in re.finditer(r'<Placemark>(.*?)</Placemark>', doc, re.S):
                b = pm.group(1)
                lat = field(b, 'Latitude'); lng = field(b, 'Longitude')
                if not lat or not lng: continue
                try: lat = float(lat); lng = float(lng)
                except ValueError: continue
                hgt = field(b, 'Height'); elv = field(b, 'Elevation')
                to_ft = lambda s: int(round(float(s) * 3.28084)) if s else 0
                try: h_ft, e_ft = to_ft(hgt), to_ft(elv)
                except ValueError: h_ft = e_ft = 0
                lit = 1 if field(b, 'Lighting').upper().startswith('Y') else 0
                out.append([round(lat, 5), round(lng, 5), e_ft, h_ft,
                            type_idx(field(b, 'Obstacle type')), lit])
    out.sort(key=lambda r: (r[0], r[1]))
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'obst.json')
    data = {'updated': datetime.date.today().isoformat(), 'types': TYPES, 'o': out}
    json.dump(data, open(dst, 'w'), separators=(',', ':'))
    sz = os.path.getsize(dst) / 1024 / 1024
    print(f'{len(out)} 障害物 → obst.json ({sz:.1f}MB)')
    from collections import Counter
    print('種別:', Counter(TYPES[r[4]] for r in out).most_common(6))
    print('最高:', max(r[2] for r in out), 'ft(標高)')

if __name__ == '__main__': main()
