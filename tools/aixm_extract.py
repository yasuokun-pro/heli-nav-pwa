#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIXM 5.1.1(SWIM AIP データ配信)から空域(Airspace)を抜き出して中間ファイルにする
=================================================================================
入力: aip/aixm_dist/AIXM_ALL_*.xml(初回全件・約840MB)。⚠ aip/ は .gitignore 済み。SWIM のデータを公開リポジトリに置かない
出力: aip/aixm_dist/airspace.json … 空域ごとの時間スライス(BASELINE/PERMDELTA)と区画(上下限・外周)
     {"src": ファイル名, "airspace": [{uuid, slices:[{interp, seq, corr, begin, end, type, localType, designator, name,
                                                      comps:[{op, seq, up, upUom, upRef, lo, loUom, loRef, rings:[[[lat,lng],...]]}]}]}]}
⚠ 840MB を DOM で読むとメモリが足りない。lxml.iterparse で hasMember ごとに読み捨てる
⚠ 座標は EPSG:4326 の urn 形式なので **緯度 経度** の順(posList)。GeodesicString/LineStringSegment を順につなぐ
使い方: python3 tools/aixm_extract.py [AIXM_ALL_*.xml]
"""
import os, sys, glob, json
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, '..', 'aip', 'aixm_dist')
NS = {'aixm': 'http://www.aixm.aero/schema/5.1.1', 'gml': 'http://www.opengis.net/gml/3.2',
      'message': 'http://www.aixm.aero/schema/5.1.1/message'}
A = '{%s}' % NS['aixm']; G = '{%s}' % NS['gml']


def txt(el, path):
    x = el.find(path, NS)
    return x.text.strip() if x is not None and x.text else None


def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


RAD_NM = {'[nmi_i]': 1.0, 'NM': 1.0, 'KM': 1 / 1.852, 'km': 1 / 1.852, 'M': 1 / 1852, 'm': 1 / 1852, '[mi_i]': 1.609344 / 1.852, 'MI': 1.609344 / 1.852}


def circles_of(surface):
    """CircleByCenterPoint(真円)→ [{c:[lat,lng], r:NM}]。⚠ 半径の単位は UCUM の "[nmi_i]"(海里)"""
    out = []
    for c in surface.iterfind('.//gml:CircleByCenterPoint', NS):
        pos = c.find('gml:pos', NS); rad = c.find('gml:radius', NS)
        if pos is None or rad is None: continue
        la, lo = [float(x) for x in pos.text.split()[:2]]
        out.append({'c': [round(la, 6), round(lo, 6)], 'r': round(float(rad.text) * RAD_NM.get(rad.get('uom'), 1.0), 4)})
    return out


def ring_of(surface):
    """Surface → 外周リングの配列(PolygonPatch ごと)。curveMember の線をつないで閉じる(真円だけのリングは circles_of で拾う)"""
    out = []
    for patch in surface.iterfind('.//gml:PolygonPatch', NS):
        ext = patch.find('gml:exterior', NS)
        if ext is None: continue
        if ext.find('.//gml:CircleByCenterPoint', NS) is not None and ext.find('.//gml:posList', NS) is None: continue
        pts = []
        for pl in ext.iterfind('.//gml:posList', NS):
            v = [float(x) for x in pl.text.split()]
            for i in range(0, len(v) - 1, 2):
                p = [round(v[i], 6), round(v[i + 1], 6)]
                if not pts or pts[-1] != p: pts.append(p)
        for pp in ext.iterfind('.//gml:pos', NS):            # 単独の点(稀)
            v = [float(x) for x in pp.text.split()]
            p = [round(v[0], 6), round(v[1], 6)]
            if not pts or pts[-1] != p: pts.append(p)
        if len(pts) >= 3: out.append(pts)
    return out


def comp_of(gc):
    vol = gc.find('aixm:theAirspaceVolume/aixm:AirspaceVolume', NS)
    c = {'op': txt(gc, 'aixm:operation'), 'seq': int(txt(gc, 'aixm:operationSequence') or 0)}
    if vol is None: return c
    for k, tag in (('up', 'upperLimit'), ('lo', 'lowerLimit')):
        e = vol.find('aixm:' + tag, NS)
        if e is not None:
            c[k] = num(e.text) if e.text else e.text
            c[k + 'Uom'] = e.get('uom')
            if e.text and num(e.text) is None: c[k] = e.text.strip()    # GND / UNL など。⚠ 0 は数値(not で見ると '0' の文字列になる)
        c[k + 'Ref'] = txt(vol, 'aixm:%sReference' % tag)
    s = vol.find('aixm:horizontalProjection/aixm:Surface', NS)
    c['rings'] = ring_of(s) if s is not None else []
    c['circles'] = circles_of(s) if s is not None else []
    ref = vol.find('.//aixm:contributorAirspace', NS)
    if ref is not None: c['contrib'] = 1                          # 他の空域を参照する形(今は数えるだけ)
    return c


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(DIR, 'AIXM_ALL_*.xml')))[-1]
    out = []
    for ev, el in etree.iterparse(src, events=('end',), tag=A + 'Airspace', huge_tree=True):
        uuid = txt(el, 'gml:identifier')
        sl = []
        for ts in el.iterfind('aixm:timeSlice/aixm:AirspaceTimeSlice', NS):
            vt = ts.find('gml:validTime/gml:TimePeriod', NS)
            end = vt.find('gml:endPosition', NS) if vt is not None else None
            sl.append({'interp': txt(ts, 'aixm:interpretation'), 'seq': int(txt(ts, 'aixm:sequenceNumber') or 0),
                       'corr': int(txt(ts, 'aixm:correctionNumber') or 0),
                       'begin': txt(vt, 'gml:beginPosition') if vt is not None else None,
                       'end': end.text.strip() if end is not None and end.text else None,
                       'type': txt(ts, 'aixm:type'), 'localType': txt(ts, 'aixm:localType'),
                       'designator': txt(ts, 'aixm:designator'), 'name': txt(ts, 'aixm:name'),
                       'comps': [comp_of(gc) for gc in ts.iterfind('aixm:geometryComponent/aixm:AirspaceGeometryComponent', NS)]})
        out.append({'uuid': uuid, 'slices': sl})
        el.clear()
        while el.getprevious() is not None: del el.getparent()[0]
    dst = os.path.join(DIR, 'airspace.json')
    json.dump({'src': os.path.basename(src), 'airspace': out}, open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} airspace / {sum(len(a["slices"]) for a in out)} slices → {dst} ({os.path.getsize(dst)//1024} KB)')


if __name__ == '__main__':
    main()
