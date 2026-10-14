#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
awy.json(PDF の ENR 3.1/3.3 から起こした航空路)を AIXM(SWIM AIP データ配信)で直す(v6-218)
==========================================================================================
1) MEA: 両方にある区間は AIXM の値にする(inh=前の区間から継いだ印も外す)。
   ⚠ PDF 版は MEA を「変わるところにしか書かない」表から読んでいて、矢印(↑6000 / FL230↓ = 上の区間/下の区間)を
     取り違えたり、継ぎ方を誤ったりしていた(V30 HAKODATE–TSURU: PDF 版 6000 → 正しくは FL230)
2) 区間の並びが違う経路(A590 の YOSHI・V28 の OYE が抜けていた)は AIXM の順に組み直す。区間の他の属性(奇偶・MOCA…)は
   端点が同じ区間から引き継ぐ
3) AIXM にしか無い経路(L512・M523・M750・N884・Q1・Z101・Z102)を足す(k='RNAV')
⚠ 直行経路(DCT・ENR 3.5.1)は AIXM では designatorSecondLetter が OTHER で「運航には使用不可」の識別なので触らない
使い方: python3 tools/fix_awy_aixm.py [--at …] [--write]
"""
import os, sys, json, glob, math, datetime, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aixm_ifr_compare import load
from gen_ils_aixm import t, href, pos, num

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def meaft(v):
    """アプリの MEA(6000 / 'FL150' / 'FL60')を ft に。index.html の meaFt と同じ読み方"""
    if v is None or v == '': return None
    if isinstance(v, (int, float)): return int(v)
    v = str(v).upper().strip()
    if v.startswith('FL'):
        try: return int(v[2:]) * 100
        except ValueError: return None
    try: return int(float(v))
    except ValueError: return None


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    src = sorted(glob.glob(os.path.join(ROOT, 'aip', 'aixm_dist', 'AIXM_ALL_*.xml')))[-1]
    F = load(src, at)
    pt = {}
    for u, ts in F['DesignatedPoint'].items(): pt[u] = {'id': t(ts, 'aixm:designator'), 'name': t(ts, 'aixm:designator'), 'p': pos(ts), 'nav': 0}
    for u, ts in F['Navaid'].items(): pt[u] = {'id': t(ts, 'aixm:designator'), 'name': (t(ts, 'aixm:name') or t(ts, 'aixm:designator') or '').upper(), 'p': pos(ts), 'nav': 1}
    rname = {}
    for u, ts in F['Route'].items():
        sl = t(ts, 'aixm:designatorSecondLetter') or ''
        if sl.startswith('OTHER'): continue
        rname[u] = (t(ts, 'aixm:designatorPrefix') or '') + sl + (t(ts, 'aixm:designatorNumber') or '')
    segs = collections.defaultdict(list)
    for u, ts in F['RouteSegment'].items():
        r = rname.get(href(ts, 'aixm:routeFormed'))
        a = href(ts, 'aixm:start/aixm:EnRouteSegmentPoint/aixm:pointChoice_fixDesignatedPoint') or href(ts, 'aixm:start/aixm:EnRouteSegmentPoint/aixm:pointChoice_navaidSystem')
        b = href(ts, 'aixm:end/aixm:EnRouteSegmentPoint/aixm:pointChoice_fixDesignatedPoint') or href(ts, 'aixm:end/aixm:EnRouteSegmentPoint/aixm:pointChoice_navaidSystem')
        if not r or a not in pt or b not in pt: continue
        mea, mu = num(ts, 'aixm:minimumEnrouteAltitude')
        if mea is not None and mu == 'FL': mea *= 100
        ln, _ = num(ts, 'aixm:length'); mg, _ = num(ts, 'aixm:magneticTrack')
        segs[r].append({'a': a, 'b': b, 'mea': int(mea) if mea else None, 'dist': ln, 'mag': int(mg) if mg is not None else None})
    W = json.load(open(os.path.join(ROOT, 'awy.json')))
    # 今の awy.json の点の呼び方(navaid は長い名前+id)を id から引けるように
    nm_of_id = {}
    for r in W['f']:
        for p in r['pts']: nm_of_id.setdefault(p.get('id') or p['n'], p['n'])
    allpts = [p for r in W['f'] for p in r['pts']]
    def pname(u):
        # ⚠ 同じ点を別の名前で作ると経路探索で別の節点になり、乗り継げなくなる(MYE と MATSUYAMA)。
        #   id で引けなければ、**同じ位置(100m 以内)**にある今の点の名前に合わせる
        if pt[u]['id'] in nm_of_id: return nm_of_id[pt[u]['id']]
        la, lo = pt[u]['p']
        k = math.cos(math.radians(la))
        near = min(allpts, key=lambda q: (q['lat'] - la) ** 2 + ((q['lng'] - lo) * k) ** 2)
        if math.hypot((near['lat'] - la) * 110540, (near['lng'] - lo) * 111320 * k) < 100: return near['n']
        return pt[u]['name'] if pt[u]['nav'] else pt[u]['id']
    def ppt(u):
        o = {'n': pname(u), 'lat': round(pt[u]['p'][0], 6), 'lng': round(pt[u]['p'][1], 6)}
        # ⚠ 航空路の端点の navaid が DesignatedPoint(designator=MYE など)で載っていることがある。名前と違えば id を付ける
        if pt[u]['nav'] or o['n'] != pt[u]['id']: o['id'] = pt[u]['id']
        return o
    def chain(sl):
        """区間を端からつないで並べる。途切れていても(別々の鎖)全部の区間を返す: [(起点, 区間)…]"""
        adj = collections.defaultdict(list)
        for s in sl: adj[s['a']].append(s); adj[s['b']].append(s)
        seen, out = set(), []
        starts = [u for u, v in adj.items() if len(v) == 1] + list(adj)
        for st in starts:
            cur = st
            while True:
                nx = [s for s in adj[cur] if id(s) not in seen]
                if not nx: break
                s = nx[0]; seen.add(id(s)); out.append((cur, s)); cur = s['b'] if s['a'] == cur else s['a']
        return out
    stat = collections.Counter()
    names = set()
    for r in W['f']:
        if r.get('k') == 'DCT': continue
        names.add(r['n'])
        sl = segs.get(r['n'])
        if not sl: continue
        ids = {p['n']: p.get('id') or p['n'] for p in r['pts']}
        ax = {frozenset((pt[s['a']]['id'], pt[s['b']]['id'])): s for s in sl}
        mine = {frozenset((ids.get(s['a'], s['a']), ids.get(s['b'], s['b']))): s for s in r['segs']}
        if set(mine) != set(ax):
            # 組み直す: AIXM の順。属性は端点が同じ区間から、無ければ隣の区間から
            ch = chain(sl)
            pts, new, have = [], [], set()
            for i, (cur, s) in enumerate(ch):
                nxt = s['b'] if s['a'] == cur else s['a']
                for u in (cur, nxt):
                    if u not in have: have.add(u); pts.append(ppt(u))
                k = frozenset((pt[cur]['id'], pt[nxt]['id']))
                base = dict(mine.get(k) or (new[-1] if new else r['segs'][0]))
                base.pop('inh', None)
                base.update({'a': pname(cur), 'b': pname(nxt), 'mea': s['mea'] or base.get('mea'), 'dist': s['dist'] or base.get('dist')})
                if k not in mine: base['rmk'] = 'AIXM で追加'; stat['区間を追加'] += 1
                new.append(base)
            print(f"  組み直し {r['n']}: 区間 {len(r['segs'])} → {len(new)}  "
                  f"消えた {sorted('-'.join(sorted(k)) for k in set(mine) - set(ax))}  増えた {sorted('-'.join(sorted(k)) for k in set(ax) - set(mine))}")
            r['pts'], r['segs'] = pts, new
            stat['組み直した経路'] += 1
            continue
        for k, s in mine.items():
            a = ax[k]
            if a['mea'] and meaft(s.get('mea')) != a['mea']:
                stat['MEA を直した区間'] += 1
                if meaft(s.get('mea')) is not None and abs(meaft(s.get('mea')) - a['mea']) >= 1000: stat['うち1000ft以上違う'] += 1
                s['mea'] = ('FL%d' % (a['mea'] // 100)) if isinstance(s.get('mea'), str) and str(s['mea']).upper().startswith('FL') else a['mea']
                if isinstance(s.get('inh'), list):
                    s['inh'] = [x for x in s['inh'] if x != 'mea'] or None
                    if s['inh'] is None: s.pop('inh')
    for rn in sorted(set(segs) - names):
        ch = chain(segs[rn])
        if not ch: continue
        pts, new, have = [], [], set()
        for i, (cur, s) in enumerate(ch):
            nxt = s['b'] if s['a'] == cur else s['a']
            for u in (cur, nxt):
                if u not in have: have.add(u); pts.append(ppt(u))
            new.append({'a': pname(cur), 'b': pname(nxt), 'dist': s['dist'], 'mea': s['mea'], 'mag': s['mag'], 'rmk': 'AIXM で追加'})
        W['f'].append({'n': rn, 'pts': pts, 'segs': new, 'k': 'RNAV' if rn[0] in 'LMNQYZ' else 'LOW'})
        stat['経路を追加'] += 1
    print(dict(stat))
    if '--write' in sys.argv:
        W['src'] = W.get('src', '') + ' + MEA・区間は SWIM AIP データ配信(AIXM 5.1.1) ' + os.path.basename(src).replace('.xml', '')
        json.dump(W, open(os.path.join(ROOT, 'awy.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        print('awy.json を更新', len(W['f']), '本')


if __name__ == '__main__':
    main()
