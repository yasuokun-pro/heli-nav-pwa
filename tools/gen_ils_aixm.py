#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ILS の最終進入経路を AIXM(SWIM AIP データ配信)から作る → ils.json(PDF からの tools/gen_ils.py を置き換え・v6-217)
=========================================================================================================
AIXM では ILS がいくつもの地物に分かれていて、xlink(urn:uuid)でつながっている:
  Navaid(type ILS / ILS_DME …・designator=識別符号)
    ├ navaidEquipment → Localizer(位置・周波数・trueBearing) / Glidepath(位置・slope=GP角・rdh)
    ├ runwayDirection → RunwayDirection(designator=滑走路番号・trueBearing) ─ usedRunway → Runway ─ associatedAirportHeliport → AirportHeliport(ICAO)
    └ servedAirport   → AirportHeliport
  RunwayCentrelinePoint(role=THR / DISTHR・onRunway → RunwayDirection)… 滑走路末端の位置と標高
出力は今の ils.json と同じ形: {icao, rwy, id, f, ang, rdh, elev, crs(真方位・進入機の向き), thr:[lat,lng], loc:[lat,lng], src:'aixm'}
⚠ 進入コースは RunwayDirection の真方位。LOC 自身に trueBearing があればそちらを優先(オフセットの LOC 用)
⚠ THR は DISTHR(移設末端)があればそれ(GP はそちらに合わせてある)
使い方: python3 tools/gen_ils_aixm.py [--at 2026-10-14] [--compare] [--write]
"""
import os, sys, json, math, glob, datetime
from lxml import etree

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
NS = {'aixm': 'http://www.aixm.aero/schema/5.1.1', 'gml': 'http://www.opengis.net/gml/3.2', 'xlink': 'http://www.w3.org/1999/xlink'}
A = '{%s}' % NS['aixm']
WANT = ['Navaid', 'Localizer', 'Glidepath', 'RunwayDirection', 'Runway', 'AirportHeliport', 'RunwayCentrelinePoint']


def t(el, p):
    x = el.find(p, NS)
    return x.text.strip() if x is not None and x.text else None


def href(el, p):
    x = el.find(p, NS)
    v = x.get('{%s}href' % NS['xlink']) if x is not None else None
    return v.replace('urn:uuid:', '') if v else None


def pick(el, at):
    """その日に有効な BASELINE の timeSlice"""
    best = None
    for ts in el.iterfind('aixm:timeSlice/*', NS):
        if t(ts, 'aixm:interpretation') != 'BASELINE': continue
        b = t(ts, 'gml:validTime/gml:TimePeriod/gml:beginPosition')
        e = ts.find('gml:validTime/gml:TimePeriod/gml:endPosition', NS)
        e = e.text.strip() if e is not None and e.text else None
        if b and b <= at and (not e or e > at):
            sq = int(t(ts, 'aixm:sequenceNumber') or 0), int(t(ts, 'aixm:correctionNumber') or 0)
            if best is None or sq > best[0]: best = (sq, ts)
    return best[1] if best else None


def pos(ts):
    p = t(ts, './/aixm:ElevatedPoint/gml:pos') or t(ts, './/aixm:Point/gml:pos')
    return [float(x) for x in p.split()[:2]] if p else None


def num(ts, p):
    x = ts.find(p, NS)
    if x is None or not x.text: return None, None
    try: return float(x.text), x.get('uom')
    except ValueError: return None, None


def load(src, at):
    F = {k: {} for k in WANT}
    for ev, el in etree.iterparse(src, events=('end',), tag=[A + k for k in WANT], huge_tree=True):
        k = etree.QName(el).localname
        uid = t(el, 'gml:identifier')
        ts = pick(el, at)
        if ts is not None and uid: F[k][uid] = ts
        el.clear()
        while el.getprevious() is not None: del el.getparent()[0]
    return F


def brg(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2); x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def build(F):
    thr = {}
    for ts in F['RunwayCentrelinePoint'].values():
        role = t(ts, 'aixm:role'); rd = href(ts, 'aixm:onRunway')
        if role not in ('THR', 'DISTHR') or not rd: continue
        p = pos(ts)
        el, u = num(ts, './/aixm:ElevatedPoint/aixm:elevation')
        if el is not None and u == 'M': el = el / 0.3048
        if p and (rd not in thr or role == 'DISTHR'): thr[rd] = {'p': p, 'elev': el, 'role': role}
    ap_of_rwy = {uid: href(ts, 'aixm:associatedAirportHeliport') for uid, ts in F['Runway'].items()}
    icao = {uid: (t(ts, 'aixm:locationIndicatorICAO') or t(ts, 'aixm:designator')) for uid, ts in F['AirportHeliport'].items()}
    # ⚠ 日本の AIXM では LOC・GP・DME が**別々の Navaid**(name "ILS-LOC 16R" / "ILS-GP 16R" / "ILS-DME 16R")。
    #   同じ runwayDirection を指すものをまとめて1本の ILS にする
    grp = {}
    for uid, ts in F['Navaid'].items():
        ty = t(ts, 'aixm:type') or ''
        if not (ty.startswith('ILS') or ty.startswith('LOC') or ty == 'OTHER'): continue
        rd = href(ts, 'aixm:runwayDirection')
        if not rd: continue
        g = grp.setdefault(rd, {'loc': None, 'gp': None, 'id': None, 'ap': href(ts, 'aixm:servedAirport')})
        for c in ts.iterfind('aixm:navaidEquipment/aixm:NavaidComponent', NS):
            e = href(c, 'aixm:theNavaidEquipment')
            if e in F['Localizer'] and g['loc'] is None: g['loc'] = F['Localizer'][e]; g['id'] = t(ts, 'aixm:designator')
            if e in F['Glidepath'] and g['gp'] is None: g['gp'] = F['Glidepath'][e]
    out, miss = [], []
    for rd, g in grp.items():
        loc, gp, rdt = g['loc'], g['gp'], F['RunwayDirection'].get(rd)
        rwy = t(rdt, 'aixm:designator') if rdt is not None else '?'
        ap = (icao.get(ap_of_rwy.get(href(rdt, 'aixm:usedRunway'))) if rdt is not None else None) or icao.get(g['ap'])
        if loc is None or gp is None or rdt is None:
            if loc is not None or gp is not None: miss.append(f"{ap} {rwy}: LOC={loc is not None} GP={gp is not None}")
            continue
        T = thr.get(rd)
        lp = pos(loc)
        if T is None or lp is None: miss.append(f'{ap} {rwy}: THR={T is not None} LOC位置={lp is not None}'); continue
        tb, _ = num(loc, 'aixm:trueBearing')
        rb, _ = num(rdt, 'aixm:trueBearing')
        crs = tb if tb is not None else rb if rb is not None else brg(T['p'], lp)
        ang, _ = num(gp, 'aixm:slope'); rdh, ru = num(gp, 'aixm:rdh')
        if rdh is not None and ru == 'M': rdh = rdh / 0.3048
        f, _ = num(loc, 'aixm:frequency')
        # ⚠ GP の基準は**移設末端**のことがある(羽田 16L/16R/34R)が、AIXM の RunwayCentrelinePoint には物理の THR しか無い。
        #   物理の THR を使うと 400〜500m(GP 上で約70ft)ずれるので、THR は GP アンテナを中心線に下ろした点から RDH/tan だけ手前に置く
        #   (gen_ils.py と同じ考え方。位置・方位・RDH・GP角は AIXM の正確な値)。標高だけ AIXM の THR から
        gpp = pos(gp)
        # 中心線は **AIXM の物理 THR を通る真方位の線**(LOC が中心線上に無い滑走路があるので LOC を通さない)
        k = math.cos(math.radians(T['p'][0]))
        ux, uy = math.sin(math.radians(crs)), math.cos(math.radians(crs))
        rel = lambda q: ((q[1] - T['p'][1]) * 111320 * k, (q[0] - T['p'][0]) * 110540)
        le, ln = rel(lp)
        loc_off = abs(le * uy - ln * ux)                        # LOC の中心線からの横ずれ(m)
        if loc_off > 300 or not (0 < le * ux + ln * uy < 6000):    # LOC は向こう側の末端の先(滑走路長+数百m)
            # ⚠ 宇都宮 RWY19 に下総の LOC(ISH)が付いていた(AIXM の関連づけの誤り・80km 離れている)。中心線から外れた LOC は出さない
            miss.append(f'{ap} {rwy}: LOC が中心線から {loc_off:.0f}m 外れている/THR から 6km の範囲に無い({t(loc, "aixm:designator")}) → 出さない'); continue
        if gpp:
            ge, gn = rel(gpp)
            along = ge * ux + gn * uy                            # THR から見た GP アンテナ(滑走路の内側が正)
            setb = (rdh or 50) * 0.3048 / math.tan(math.radians(ang or 3.0))
            dm = along - setb                                    # GP の基準になる末端(移設末端なら THR より内側)
            eff = [T['p'][0] + dm * uy / 110540, T['p'][1] + dm * ux / (111320 * k)]
            dphys = abs(dm)
        else:
            eff, dphys = T['p'], 0
        out.append({'icao': ap, 'rwy': rwy, 'id': t(loc, 'aixm:designator') or g['id'] or '', 'f': f'{f:g}MHz' if f else '',
                    'ang': ang or 3.0, 'angAs': 0 if ang else 1, 'rdh': round(rdh) if rdh else 50, 'rdhAs': 0 if rdh else 1,
                    'elev': round(T['elev'], 1) if T['elev'] is not None else None, 'elevAd': 0, 'crs': round(crs, 2),
                    'crsBy': 'AIXM ' + ('LOC' if tb is not None else 'RWY' if rb is not None else 'THR→LOC'),
                    'thr': [round(eff[0], 6), round(eff[1], 6)], 'loc': [round(lp[0], 6), round(lp[1], 6)],
                    **({'dthr': round(dphys)} if dphys > 150 else {}), 'src': 'aixm'})
    # 同じ滑走路に ILS が2つ(Y/Z)あれば1つに
    seen, uniq = set(), []
    for o in sorted(out, key=lambda o: (o['icao'], o['rwy'])):
        if (o['icao'], o['rwy']) in seen: continue
        seen.add((o['icao'], o['rwy'])); uniq.append(o)
    return uniq, miss


def dist_m(a, b):
    k = math.cos(math.radians(a[0]))
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * k)


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    src = sorted(glob.glob(os.path.join(ROOT, 'aip', 'aixm_dist', 'AIXM_ALL_*.xml')))[-1]
    F = load(src, at)
    out, miss = build(F)
    print(f'{at} 時点: AIXM の ILS {len(out)} 本 / {len(set(o["icao"] for o in out))} 飛行場({os.path.basename(src)})')
    for m in miss[:20]: print('  対象外:', m)
    if '--compare' in sys.argv or '--write' not in sys.argv:
        old = {(o['icao'], o['rwy']): o for o in json.load(open(os.path.join(ROOT, 'ils.json')))['ils']}
        new = {(o['icao'], o['rwy']): o for o in out}
        print(f"\n{'ILS':10} {'THR差m':>7} {'方位差°':>7} {'GP角':>11} {'RDH':>9} {'THR標高':>13}")
        for k in sorted(set(old) & set(new)):
            o, n = old[k], new[k]
            d = dist_m(o['thr'], n['thr']); dc = abs((o['crs'] - n['crs'] + 540) % 360 - 180)
            flag = d > 60 or dc > 0.5 or o['ang'] != n['ang'] or abs((o['rdh'] or 0) - (n['rdh'] or 0)) > 2 or (o['elev'] is not None and n['elev'] is not None and abs(o['elev'] - n['elev']) > 5)
            if flag or o.get('angAs') or o.get('rdhAs') or o.get('elevAd'):
                print(f"{k[0]} {k[1]:4} {d:7.0f} {dc:7.2f} {o['ang']}{'(仮)' if o.get('angAs') else ''}→{n['ang']:<5} {o['rdh']}{'(仮)' if o.get('rdhAs') else ''}→{n['rdh']:<4} "
                      f"{o['elev']}{'(AD)' if o.get('elevAd') else ''}→{n['elev']}")
        print('\n今の ils.json だけ:', sorted(set(old) - set(new)))
        print('AIXM だけ:', sorted(set(new) - set(old)))
    if '--write' in sys.argv:
        # AIXM に無い(または関連づけが壊れていて外した)ものは、PDF から作った今の版を残す(RJFN 28・RJSM 28・RJTL 19)
        have = set((o['icao'], o['rwy']) for o in out)
        keep = [dict(o, src='pdf') for o in json.load(open(os.path.join(ROOT, 'ils.json')))['ils'] if (o['icao'], o['rwy']) not in have and o.get('src') != 'aixm']
        if keep: print('  PDF 版を残す:', [(o['icao'], o['rwy']) for o in keep])
        out = sorted(out + keep, key=lambda o: (o['icao'], o['rwy']))
        json.dump({'eff': os.path.basename(src).replace('.xml', ''), 'src': 'SWIM AIP データ配信(AIXM 5.1.1)', 'ils': out},
                  open(os.path.join(ROOT, 'ils.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        print('ils.json を更新', len(out), '本')


if __name__ == '__main__':
    main()
