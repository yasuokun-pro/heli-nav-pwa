#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IFR 計画のデータ(fix.json / 航法施設 / awy.json)を AIXM(SWIM AIP データ配信)と突き合わせる(検算)
=====================================================================================================
・FIX: fix.json の各点を DesignatedPoint(designator 一致)と位置で比べる
・航法施設: NAVAIDS(ENR 4.1・index.html)+ adnav.json(AD 2.19)を Navaid(designator 一致・同じ種類)と比べる
・航空路: awy.json の各経路の区間(端点の組)を RouteSegment と比べる。MEA も
出力: aip/aixm_dist/ifr_compare.json(詳細)と画面の要約。AIXM 側の誤りらしいものは「AIXM?」として別に出す
使い方: python3 tools/aixm_ifr_compare.py [--at 2026-10-14]
"""
import os, sys, json, math, glob, re, datetime, collections
from lxml import etree

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
NS = {'aixm': 'http://www.aixm.aero/schema/5.1.1', 'gml': 'http://www.opengis.net/gml/3.2', 'xlink': 'http://www.w3.org/1999/xlink'}
A = '{%s}' % NS['aixm']
WANT = ['DesignatedPoint', 'Navaid', 'Route', 'RouteSegment']
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_ils_aixm import t, href, pick, pos, num


def load(src, at):
    F = {k: {} for k in WANT}
    for ev, el in etree.iterparse(src, events=('end',), tag=[A + k for k in WANT], huge_tree=True):
        k = etree.QName(el).localname; uid = t(el, 'gml:identifier'); ts = pick(el, at)
        if ts is not None and uid: F[k][uid] = ts
        el.clear()
        while el.getprevious() is not None: del el.getparent()[0]
    return F


def dist_m(a, b):
    k = math.cos(math.radians(a[0]))
    return math.hypot((a[0] - b[0]) * 110540, (a[1] - b[1]) * 111320 * k)


NAVT = {'VOR': 'VOR', 'VOR_DME': 'VOR/DME', 'VORTAC': 'VORTAC', 'TACAN': 'TACAN', 'NDB': 'NDB', 'DME': 'DME', 'NDB_DME': 'NDB'}


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    src = sorted(glob.glob(os.path.join(ROOT, 'aip', 'aixm_dist', 'AIXM_ALL_*.xml')))[-1]
    F = load(src, at)
    rep = {'fix': [], 'nav': [], 'awy': [], 'aixm': []}
    # ── FIX
    dp = {}
    for uid, ts in F['DesignatedPoint'].items():
        d = t(ts, 'aixm:designator'); p = pos(ts)
        if d and p: dp.setdefault(d, []).append((p, t(ts, 'aixm:type'), uid))
    FIX = json.load(open(os.path.join(ROOT, 'fix.json')))['f']
    far, miss = [], []
    navname = {}
    for uid, ts in F['Navaid'].items():
        nm = (t(ts, 'aixm:name') or '').upper(); p = pos(ts)
        if nm and p: navname.setdefault(nm, []).append((p, 'NAV', uid))
    for f in FIX:
        c = dp.get(f['n']) or navname.get(f['n'].upper())      # fix.json には navaid 名の点(AOMORI など)も入っている
        if not c: miss.append(f['n']); continue
        d = min(dist_m([f['lat'], f['lng']], p) for p, _, _ in c)
        if d > 30: far.append((round(d), f['n']))
    far.sort(reverse=True)
    print(f"FIX: fix.json {len(FIX)} 点 / AIXM の DesignatedPoint {len(dp)} 名。位置の差 30m 超 {len(far)} 点・AIXM に無い {len(miss)} 点")
    for d, n in far[:15]: print(f'   {d:7}m  {n}')
    if miss: print('   AIXM に無い:', ', '.join(miss[:40]), '…' if len(miss) > 40 else '')
    rep['fix'] = {'far': far, 'miss': miss}
    # ── 航法施設
    nav = {}
    for uid, ts in F['Navaid'].items():
        d = t(ts, 'aixm:designator'); p = pos(ts); ty = t(ts, 'aixm:type') or ''
        if d and p: nav.setdefault(d, []).append((p, ty, t(ts, 'aixm:name'), uid))
    h = open(os.path.join(ROOT, 'index.html')).read()
    blk = h[h.index('/*NAVAIDS_GEN_START*/'):h.index('/*NAVAIDS_GEN_END*/')]
    NAVAIDS = json.loads(blk[blk.index('['):blk.rindex(']') + 1])
    AD = [v for v in json.load(open(os.path.join(ROOT, 'adnav.json')))['f'].values() if not v['t'].startswith(('ILS', 'LOC', 'GP'))]
    nfar, nmiss = [], []
    for v in NAVAIDS + AD:
        c = nav.get(v['id'])
        if not c: nmiss.append(f"{v['id']}({v['t']})"); continue
        d = min(dist_m([v['lat'], v['lng']], p) for p, _, _, _ in c)
        if d > 30: nfar.append((round(d), f"{v['id']} {v['t']} {v.get('n') or v.get('icao', '')}"))
    nfar.sort(reverse=True)
    print(f"\n航法施設: アプリ {len(NAVAIDS)}+{len(AD)} 局 / AIXM {len(nav)} 名。位置の差 30m 超 {len(nfar)}・AIXM に無い {len(nmiss)}")
    for d, n in nfar[:15]: print(f'   {d:7}m  {n}')
    if nmiss: print('   AIXM に無い:', ', '.join(nmiss[:40]))
    rep['nav'] = {'far': nfar, 'miss': nmiss}
    # ── 航空路
    name_of = {}
    for uid, ts in F['DesignatedPoint'].items(): name_of[uid] = t(ts, 'aixm:designator')
    for uid, ts in F['Navaid'].items(): name_of[uid] = t(ts, 'aixm:designator')
    rname = {}
    for uid, ts in F['Route'].items():
        sl = t(ts, 'aixm:designatorSecondLetter') or ''
        rname[uid] = (t(ts, 'aixm:designatorPrefix') or '') + (sl if not sl.startswith('OTHER') else '') + (t(ts, 'aixm:designatorNumber') or '') if not sl.startswith('OTHER') else None
    seg = collections.defaultdict(dict)
    for uid, ts in F['RouteSegment'].items():
        r = rname.get(href(ts, 'aixm:routeFormed'))
        a = href(ts, 'aixm:start/aixm:EnRouteSegmentPoint/aixm:pointChoice_fixDesignatedPoint') or href(ts, 'aixm:start/aixm:EnRouteSegmentPoint/aixm:pointChoice_navaidSystem')
        b = href(ts, 'aixm:end/aixm:EnRouteSegmentPoint/aixm:pointChoice_fixDesignatedPoint') or href(ts, 'aixm:end/aixm:EnRouteSegmentPoint/aixm:pointChoice_navaidSystem')
        if not r or not a or not b: continue
        mea, mu = num(ts, 'aixm:minimumEnrouteAltitude')
        if mea is not None and mu == 'FL': mea *= 100                 # ⚠ 単位 FL(150 = FL150)
        seg[r][frozenset((name_of.get(a), name_of.get(b)))] = mea
    AWY = json.load(open(os.path.join(ROOT, 'awy.json')))['f']
    rows = []
    for r in AWY:
        if r.get('k') == 'DCT': continue
        ids = {p['n']: p.get('id') or p['n'] for p in r['pts']}
        meaft = lambda v: (int(v[2:]) * 100 if str(v).upper().startswith('FL') else int(re.sub(r'\D', '', str(v)) or 0)) if v not in (None, '') else None
        mine = {frozenset((ids.get(s['a'], s['a']), ids.get(s['b'], s['b']))): meaft(s.get('mea')) for s in r['segs']}
        ax = seg.get(r['n'], {})
        if not ax: rows.append((r['n'], 'AIXM に経路なし', len(mine), 0, [])); continue
        only_me = [tuple(sorted(x)) for x in mine if x not in ax]
        only_ax = [tuple(sorted(x)) for x in ax if x not in mine]
        mea_d = [(tuple(sorted(x)), mine[x], ax[x]) for x in mine if x in ax and mine[x] and ax[x] and abs(mine[x] - ax[x]) >= 100]
        if only_me or only_ax or mea_d: rows.append((r['n'], f'区間 アプリだけ{len(only_me)}・AIXMだけ{len(only_ax)}・MEA差{len(mea_d)}', len(mine), len(ax), (only_me[:3], only_ax[:3], mea_d[:3])))
    names_app = set(r['n'] for r in AWY if r.get('k') != 'DCT')
    print(f"\n航空路: アプリ {len(names_app)} 本 / AIXM {len(seg)} 本(直行経路を除く)。違いのある経路 {len(rows)}")
    for r in rows[:25]: print('  ', r[0], r[1], f'(区間 {r[2]}/{r[3]})', r[4] if r[4] else '')
    extra = sorted(set(seg) - names_app)
    if extra: print('   AIXM だけにある経路:', ', '.join(extra[:40]))
    rep['awy'] = {'diff': rows, 'aixm_only': extra}
    json.dump(rep, open(os.path.join(ROOT, 'aip', 'aixm_dist', 'ifr_compare.json'), 'w'), ensure_ascii=False, indent=1, default=list)


if __name__ == '__main__':
    main()
