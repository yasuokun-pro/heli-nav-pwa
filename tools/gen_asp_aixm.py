#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管制圏(CTR)・情報圏を AIXM(SWIM AIP データ配信)から作り、index.html の ASP_POLY に差し込む
=========================================================================================
入力: aip/aixm_dist/airspace.json(tools/aixm_extract.py) / 今の index.html の ASP_POLY(特別管制区 PCA と注記の引き継ぎ用)
出力: index.html の /*ASP_POLY_GEN_START*/〜END を書き換える(--splice)。PCA は AIXM に無いので**今のものをそのまま残す**
⚠ 順番: AIRAC 更新では gen_asp.py --splice(PCA を作る)→ この gen_asp_aixm.py --splice(CTR/情報圏を差し替える)
⚠ AIXM の CTR は区画ごとに上限が違う(築城 4000/6000、那覇 2000/700、八尾…)。区画ごとに1件にする
⚠ 上限の基準が SFC(地表)の CTR がある(横田・嘉手納など)。upAgl:1 を付けて画面で「地表から」と出す
⚠ 1つの空域を2つの飛行場で共有しているもの(designator "RJCJ,RJCC" など)は先頭の ICAO で1件、残りは alias に入れる
⚠ 真円(引き算なし)は c/r(m)で出す。点列にすると拡大でカクカクする(CLAUDE.md §4.1)
使い方: python3 tools/gen_asp_aixm.py [--at 2026-10-29] [--splice]
"""
import os, sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aixm_geom import active, sections, rings_ll
from shapely.geometry import Polygon

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
IDX = os.path.join(ROOT, 'index.html')
GEO_NOTE = re.compile(r'\s*/?\s*(AIP概略円\([^)]*\)|AIP形状\([^)]*\)|小弧側|大弧側)\s*/?\s*')


def load_asp():
    s = open(IDX).read()
    a = s.index('/*ASP_POLY_GEN_START*/'); b = s.index('/*ASP_POLY_GEN_END*/')
    blk = s[a:b]
    return json.loads(blk[blk.index('['):blk.rindex(']') + 1]), s, a, b


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    D = json.load(open(os.path.join(ROOT, 'aip', 'aixm_dist', 'airspace.json')))
    AD = {x['icao']: x['n'] for x in json.load(open(os.path.join(ROOT, 'ad.json')))['f']}
    OLD, html, a0, b0 = load_asp()
    old = {}
    for o in OLD: old.setdefault((o['icao'], o['t']), []).append(o)
    out = []
    for A in D['airspace']:
        s = active(A['slices'], at)
        if not s: continue
        t = 'ctr' if s['type'] == 'CTR' else 'inf' if s['localType'] == 'INFORMATION ZONE' else None
        if not t: continue
        ids = [x.strip() for x in (s['designator'] or '').split(',') if x.strip()]
        ic = ids[-1] if len(ids) > 1 and ids[-1] in ('RJCC',) else ids[0]   # 新千歳・千歳は新千歳の名前で
        alias = [x for x in ids if x != ic]
        prev = old.get((ic, t)) or [o for x in alias for o in old.get((x, t), [])]
        jp = re.sub(r'\s*(CTR|情報圏).*$', '', prev[0]['n']) if prev else ' / '.join(AD.get(x, x) for x in ids)
        if len(ids) > 1 and not prev: jp = '・'.join(AD.get(x, x) for x in ids)
        rmk = GEO_NOTE.sub(' ', prev[0]['rmk']).strip(' /') if prev else ''
        secs, P = sections(s)
        ups = sorted(set(x['up'] for x in secs if x['up'] is not None))
        for x in secs:
            nm = f"{jp} {'CTR' if t == 'ctr' else '情報圏'}" + (f" (≤{x['up']})" if len(ups) > 1 and x['up'] != ups[-1] else '')
            base = {'n': nm, 'icao': ic, 't': t, 'up': x['up'], 'lo': x['lo'] or 0, 'rmk': rmk, 'src': 'aixm'}
            if alias: base['alias'] = alias
            if x.get('upRef') == 'SFC': base['upAgl'] = 1
            if x['circle']:
                out.append({**base, 'c': x['circle']['c'], 'r': round(x['circle']['r'] * 1852, 1)}); continue
            for rr in rings_ll(x['geom'], P):
                out.append({**base, 'pts': rr[0] if len(rr) == 1 else rr})
    pca = [o for o in OLD if o['t'] not in ('ctr', 'inf')]
    new = sorted(out, key=lambda o: (o['icao'], o['t'], -(o['up'] or 0))) + pca
    print(f'{at} 時点: CTR {sum(1 for o in out if o["t"]=="ctr")} / 情報圏 {sum(1 for o in out if o["t"]=="inf")} 件(AIXM {D["src"]}) + PCA {len(pca)} 件(従来)')
    gone = sorted(set((o['icao'], o['t']) for o in OLD if o['t'] in ('ctr', 'inf')) - set((o['icao'], o['t']) for o in out) -
                  set((al, o['t']) for o in out for al in o.get('alias', [])))
    if gone: print('  ⚠ 今のデータにあって AIXM に無い:', gone)
    added = sorted(set((o['icao'], o['t']) for o in out) - set((o['icao'], o['t']) for o in OLD))
    if added: print('  AIXM で増えたもの:', added)
    if '--splice' in sys.argv:
        src = D['src'].replace('.xml', '')
        blk = ('/*ASP_POLY_GEN_START*/\n/* 自動生成: tools/gen_asp_aixm.py(管制圏・情報圏 = SWIM AIP データ配信 ' + src +
               ')+ tools/gen_asp.py(特別管制区 PCA = AIP AD 2.17・RJTT/RJAA 特別管制区チャート) */\nconst ASP_POLY=' +
               json.dumps(new, ensure_ascii=False, separators=(',', ':')) + ';\n')
        open(IDX, 'w').write(html[:a0] + blk + html[b0:])
        print('spliced into index.html', len(new), '件')


if __name__ == '__main__':
    main()
