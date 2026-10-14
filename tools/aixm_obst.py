#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
障害物(VerticalStructure)を AIXM(SWIM AIP データ配信)から抜き出し、obst.json(AIS の AREA1 KML 由来)と突き合わせる
=====================================================================================================================
出力: aip/aixm_dist/obst_aixm.json … [lat, lng, elevFt, heightFt, type, lighted, area, name](その日に有効な BASELINE)
     --write で obst.json を AIXM の AREA1 から作り直す(形式は今と同じ [lat,lng,elevFt,heightFt,typeIdx,light])
⚠ 障害物の「area」は annotation の REMARK("AREA1 EHIME" など)。AREA1=全国の高い障害物、AREA2 以降=飛行場周辺(樹木を含む)
⚠ 高さは verticalExtent(地上高)、標高は ElevatedPoint の elevation(海抜・頂部か地表かは種類による)。単位は M/FT が混ざる
使い方: python3 tools/aixm_obst.py [--at …] [--write]
"""
import os, sys, json, glob, math, re, datetime, collections
from lxml import etree

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
NS = {'aixm': 'http://www.aixm.aero/schema/5.1.1', 'gml': 'http://www.opengis.net/gml/3.2', 'xlink': 'http://www.w3.org/1999/xlink'}
A = '{%s}' % NS['aixm']
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_ils_aixm import t, pick

TYPES = ['BUILDING', 'WINDMILL', 'TOWER', 'ANTENNA', 'CHIMNEY', 'POLE', 'CRANE', 'BRIDGE', 'MAST', 'OTHER', 'CATENARY', 'TREE']
ALIAS = {'STACK': 'CHIMNEY'}   # AIXM の煙突は STACK
A2_MIN = 100                   # AREA2(飛行場周辺)は 100ft 以上だけ入れる(全部だと12.5万件)


def tf(x, u):
    return None if x is None else x / 0.3048 if (u or '').upper() == 'M' else x


def fnum(el, p):
    e = el.find(p, NS)
    if e is None or not e.text: return None, None
    try: return float(e.text), e.get('uom')
    except ValueError: return None, None


def extract(src, at):
    out, kinds = [], collections.Counter()
    for ev, el in etree.iterparse(src, events=('end',), tag=A + 'VerticalStructure', huge_tree=True):
        ts = pick(el, at)
        if ts is not None:
            name = t(ts, 'aixm:name'); ty = (t(ts, 'aixm:type') or 'OTHER').upper(); lit = 1 if t(ts, 'aixm:lighted') == 'YES' else 0
            note = ' '.join(x.text or '' for x in ts.iterfind('.//aixm:annotation//aixm:note', NS))
            m = re.search(r'AREA\s*(\d)', note); area = int(m.group(1)) if m else 0
            for part in ts.iterfind('aixm:part/aixm:VerticalStructurePart', NS):
                h, hu = fnum(part, 'aixm:verticalExtent')
                pe = part.find('aixm:horizontalProjection_location/aixm:ElevatedPoint', NS)
                geo = 'pt'
                if pe is None:
                    pe = part.find('.//aixm:ElevatedCurve', NS); geo = 'line'
                if pe is None:
                    pe = part.find('.//aixm:ElevatedSurface', NS); geo = 'area'
                if pe is None: continue
                kinds[geo] += 1
                ps = pe.find('.//gml:pos', NS); pl = pe.find('.//gml:posList', NS)
                if ps is not None: v = [float(x) for x in ps.text.split()[:2]]
                elif pl is not None:
                    c = [float(x) for x in pl.text.split()]; v = [sum(c[0::2]) / (len(c) // 2), sum(c[1::2]) / (len(c) // 2)]
                else: continue
                e, eu = fnum(pe, 'aixm:elevation')
                out.append([round(v[0], 5), round(v[1], 5), round(tf(e, eu)) if e is not None else None, round(tf(h, hu)) if h is not None else None,
                            ty, lit, area, name, geo])
        el.clear()
        while el.getprevious() is not None: del el.getparent()[0]
    return out, kinds


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    src = sorted(glob.glob(os.path.join(ROOT, 'aip', 'aixm_dist', 'AIXM_ALL_*.xml')))[-1]
    cache = os.path.join(ROOT, 'aip', 'aixm_dist', 'obst_aixm.json')
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(src) and '--fresh' not in sys.argv:
        O = json.load(open(cache))['o']; kinds = {}
    else:
        O, kinds = extract(src, at)
        json.dump({'src': os.path.basename(src), 'at': at, 'o': O}, open(cache, 'w'), separators=(',', ':'))
    print(f'AIXM 障害物 {len(O)} 件 {dict(kinds)}')
    print('  地域:', dict(collections.Counter(o[6] for o in O)))
    for a in sorted(set(o[6] for o in O)):
        sub = [o for o in O if o[6] == a]
        hs = sorted(o[3] for o in sub if o[3] is not None)
        print(f'  AREA{a}: {len(sub)} 件・高さ 中央 {hs[len(hs)//2] if hs else "-"}ft・最大 {hs[-1] if hs else "-"}ft・種類 {collections.Counter(o[4] for o in sub).most_common(6)}')
    # obst.json(AREA1 KML 由来)と位置で突き合わせ(30m)
    APP = json.load(open(os.path.join(ROOT, 'obst.json')))
    a1 = [o for o in O if o[6] == 1]
    grid = collections.defaultdict(list)
    for o in a1: grid[(round(o[0], 2), round(o[1], 2))].append(o)
    def near(lat, lng):
        best = None
        for dy in (-0.01, 0, 0.01):
            for dx in (-0.01, 0, 0.01):
                for o in grid.get((round(lat + dy, 2), round(lng + dx, 2)), []):
                    d = math.hypot((o[0] - lat) * 110540, (o[1] - lng) * 111320 * math.cos(math.radians(lat)))
                    if best is None or d < best[0]: best = (d, o)
        return best
    hit, miss, hdiff = 0, [], []
    used = set()
    for x in APP['o']:
        b = near(x[0], x[1])
        if b and b[0] <= 30:
            hit += 1; used.add(id(b[1]))
            if b[1][3] is not None and abs(b[1][3] - x[3]) >= 30: hdiff.append((x, b[1]))
        else: miss.append(x)
    new = [o for o in a1 if id(o) not in used]
    print(f'\nobst.json {len(APP["o"])} 件(AREA1 KML・{APP["updated"]})と AIXM AREA1 {len(a1)} 件:')
    print(f'  一致(30m以内) {hit} / obst.json だけ {len(miss)} / AIXM だけ {len(new)} / 高さが30ft以上違う {len(hdiff)}')
    hs = sorted((o for o in new if o[3]), key=lambda o: -o[3])[:8]
    for o in hs: print('   AIXM だけ(高い順):', o[:5], o[7])
    if '--write' in sys.argv:
        # AREA1 全部 + AREA2 の 100ft 以上。同じ位置・同じ高さの重複(AIXM で273件)は1件に
        rows, seen = [], set()
        for o in sorted([o for o in O if o[6] == 1] + [o for o in O if o[6] == 2 and (o[3] or 0) >= A2_MIN], key=lambda o: -(o[3] or 0)):
            k = (o[0], o[1], o[3])
            if k in seen: continue
            seen.add(k)
            ty = ALIAS.get(o[4], o[4])
            ti = next((i for i, kk in enumerate(TYPES) if kk in ty), TYPES.index('OTHER'))
            r = [o[0], o[1], o[2] if o[2] is not None else 0, o[3] if o[3] is not None else 0, ti, o[5]]
            if o[6] == 2: r.append(2)                 # 7番目 = 2 なら飛行場周辺(AREA2)
            rows.append(r)
        J = {'updated': datetime.date.today().isoformat(), 'src': 'SWIM AIP データ配信(AIXM 5.1.1) ' + os.path.basename(src).replace('.xml', '') +
             f' AREA1 + AREA2({A2_MIN}ft以上)', 'types': TYPES, 'o': rows}
        json.dump(J, open(os.path.join(ROOT, 'obst.json'), 'w'), separators=(',', ':'))
        print('obst.json を更新', len(rows), '件(AREA2', sum(1 for r in rows if len(r) > 6), ')', os.path.getsize(os.path.join(ROOT, 'obst.json')) // 1024, 'KB')


if __name__ == '__main__':
    main()
