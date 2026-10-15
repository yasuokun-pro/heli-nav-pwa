#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
民間訓練試験空域を AIXM(SWIM AIP データ配信)から作る → civ.json
================================================================
入力: aip/aixm_dist/airspace.json(tools/aixm_extract.py)/ 今の civ.json(連絡先 fac の引き継ぎ用)
出力: civ.json(rg, n, cd, up, lo, fac, rmk, pts, src:'aixm')
⚠ PDF(ENR 5.3.1)から起こしていたときに近似だった区画(海岸線・河川・支庁界・方位線、KK4 の新幹線・高速道路の中心線)は
  AIXM では座標が全部入っている。**KK4-1〜4-8 も OSM の再現ではなく AIP の座標になる**
⚠ 同じ形を 500ft ごとに積んだ区画(KS4-1-60/-65/-70 …)は、形が同じなら1つにまとめて「n 層」と注記する
  (地図では同形が重なるだけで読めない。前の版と同じ考え方)
⚠ 区画の一部を**ある高度帯だけ**除く指定(TH13-2 の 0〜2000ft)は高度帯ごとに分ける(aixm_geom.sections)
使い方: python3 tools/gen_civ_aixm.py [--at 2026-10-29] [--write]
"""
import os, sys, json, re, glob, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aixm_geom import active, sections, rings_ll

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
RG = {'HK': '北海道', 'TH': '東北', 'KK': '関東/甲信越', 'CK': '中部/近畿', 'CS': '中国/四国', 'KS': '九州', 'SM': '下地島'}
RG_OLD = {v: k for k, v in RG.items()}   # 下地島は前の版でも AIXM と同じ SM として引く


def pdf_fac():
    """ENR 5.3.1 の表の Facility 欄を**罫線で**読む(pdfplumber)→ {'TH2-4': 'Communication Facility Odate Radio 118.75MHz', …}
    ⚠ Facility は複数区画で縦結合されている。結合セルは下の行で None になるので上の値を継ぐ(ページをまたいだら継がない:
      AIP はページの頭で必ず書き直している)。
    ⚠ 以前は前の版(pdftotext の列位置)から引き継ぎ、無ければ「同じ番号の組」から借りていたが、借りた先が違っていた
      (TH13-4-7〜10 は Tokyo Control でなく Sendai TCA、TH2-4 は Odate Radio、KS3-4-5 は Fukuoka APP…)"""
    try:
        import pdfplumber
    except ImportError:
        return {}
    pdfs = sorted(glob.glob(os.path.join(ROOT, 'aip', '1_AIP (PDF)', '*', 'ENR_*.pdf')))
    if not pdfs: return {}
    out = {}
    with pdfplumber.open(pdfs[-1]) as pdf:
        for pg in pdf.pages:
            if 'ENR 5.3-' not in (pg.extract_text() or '')[:80]: continue
            for t in pg.extract_tables():
                if not t or (t[0][0] or '').strip() != 'Name': continue
                cd = fac = None
                for r in t[1:]:
                    if len(r) < 5: continue
                    m = re.search(r'\(([A-Z]{2})\)', r[0] or '')
                    if m: cd = m.group(1)
                    if r[4] is not None: fac = r[4]
                    n = (r[1] or '').strip()
                    if cd and n and fac:
                        f = ' '.join(fac.split())
                        f = re.sub(r'Controll?ing ?Facility', 'Controlling Facility', f).replace('CommunicationFacility', 'Communication Facility')
                        out[cd + n] = f
    return out


def main():
    at = (sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else datetime.date.today().isoformat()) + 'T00:00:00Z'
    D = json.load(open(os.path.join(ROOT, 'aip', 'aixm_dist', 'airspace.json')))
    OLD = json.load(open(os.path.join(ROOT, 'civ.json')))
    fac = {}
    for f in OLD['f']:
        cd = f.get('cd') or RG_OLD.get(f['rg'], '')
        for part in re.split(r'〜', f['n']):                  # 「2-4〜3-2」のようにまとめた名前も個々に引けるように
            fac.setdefault(cd + part.strip(), f.get('fac', ''))
        fac.setdefault(cd + f['n'], f.get('fac', ''))
    raw = []
    for A in D['airspace']:
        s = active(A['slices'], at)
        if not s or s['localType'] != 'CIVIL TRAINING AND TESTING AREA': continue
        d = (s['designator'] or '').strip()
        m = re.match(r'([A-Z]+)(.*)$', d)
        cd, n = m.group(1), m.group(2)
        secs, P = sections(s)
        for x in secs:
            for rr in rings_ll(x['geom'], P):
                raw.append({'cd': cd, 'n': n, 'up': x['up'], 'lo': x['lo'] or 0, 'pts': rr[0] if len(rr) == 1 else rr, 'sub': x['subtracted']})
    # 連絡先は AIXM に無い。ENR 5.3.1 の表(最新の PDF)を正とし、読めなかったものだけ前の版から引き継ぐ
    PF = pdf_fac()
    st = {'pdf': 0, 'diff': []}
    print(f'  ENR 5.3.1 の表から連絡先 {len(PF)} 区画')
    # 同じ形の積み重ね(KS4-1-60/-65/…)をまとめる: 末尾の "-数字" を外した名前で、外周がほぼ同じもの
    out, used = [], set()
    key = lambda r: json.dumps(r['pts'][:3] if isinstance(r['pts'][0][0], float) else r['pts'][0][:3])
    for i, r in enumerate(raw):
        if i in used: continue
        base = re.sub(r'-\d{2}$', '', r['n']) if re.search(r'-\d{2}$', r['n']) else None
        grp = [r]
        if base:
            for j in range(i + 1, len(raw)):
                q = raw[j]
                if j in used or q['cd'] != r['cd']: continue
                if re.sub(r'-\d{2}$', '', q['n']) == base and len(q['pts']) == len(r['pts']) and key(q) == key(r):
                    grp.append(q); used.add(j)
        lo = min(g['lo'] for g in grp); up = max((g['up'] for g in grp if g['up'] is not None), default=None)
        nm = r['n'] if len(grp) == 1 else f"{base}({'・'.join(sorted({g['n'].split('-')[-1] for g in grp}))})"
        rmk = (f'同じ形を {len(grp)} 層に分けて公示({lo:,}〜{up:,}ft)。区分ごとの高度は AIP で確認' if len(grp) > 1 else '')
        fc = PF.get(r['cd'] + r['n']) or fac.get(r['cd'] + r['n']) or fac.get(r['cd'] + (base or r['n'])) or ''
        if PF and r['cd'] + r['n'] in PF:
            st['pdf'] += 1
            old = fac.get(r['cd'] + r['n']) or ''
            if old and ' '.join(old.split()).replace(' - ', ' ') != PF[r['cd'] + r['n']].replace(' - ', ' '): st['diff'].append((r['cd'] + r['n'], old, PF[r['cd'] + r['n']]))
        if not fc:
            # ⚠ AIXM には連絡先が無い(空域を参照するサービスも無い)。同じ番号の組(KS13-x など)は連絡先が同じなので借りる
            grp0 = r['cd'] + r['n'].split('-')[0] + '-'
            fc = next((v for k, v in fac.items() if k.startswith(grp0) and v), '')
            if fc: fc += '(同じ組の区画から)'
        f = {'rg': RG.get(r['cd'], r['cd']), 'cd': r['cd'], 'n': nm, 'up': up, 'lo': lo,
             'fac': fc, 'rmk': rmk, 'pts': r['pts'], 'src': 'aixm'}
        if r['cd'] == 'KK' and r['n'].startswith('4-'): f['lbl'] = 1     # 通報で区分名を言うので拡大したら名前を出す
        out.append(f)
    out.sort(key=lambda f: (list(RG).index(f['cd']) if f['cd'] in RG else 99, [int(x) if x.isdigit() else 0 for x in re.findall(r'\d+', f['n'])]))
    print(f"  連絡先を PDF の表で引けた {st['pdf']} / {len(out)} 区画。前の版と違ったもの {len(st['diff'])}")
    for k, a, b in st['diff']: print(f'    {k}: {a}  →  {b}')
    nofac = sum(1 for f in out if not f['fac'])
    if nofac: print('  連絡先なし:', ', '.join(f['cd'] + f['n'] for f in out if not f['fac']))
    print(f'{at} 時点: 民間訓練試験空域 {len(out)} 区画(元の区分 {len(raw)}・AIXM {D["src"]})。連絡先を引き継げなかったもの {nofac}')
    if '--write' in sys.argv:
        J = {'eff': D['src'].replace('.xml', ''), 'src': 'SWIM AIP データ配信(AIXM 5.1.1)・AIP ENR 5.3.1', 'f': out}
        json.dump(J, open(os.path.join(ROOT, 'civ.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        print('civ.json を更新', os.path.getsize(os.path.join(ROOT, 'civ.json')) // 1024, 'KB')


if __name__ == '__main__':
    main()
