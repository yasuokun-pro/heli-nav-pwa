#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
進入管制区・ターミナルコントロールエリア 生成 (aca.json)
========================================================
出典: AIP Japan **各飛行場の AD 2.17 ATS AIRSPACE の添付チャート**
      (◯◯進入管制区 Approach Control Area / ◯◯ターミナルコントロールエリア)

  ⚠ **AD 2.17 の表には座標が無い**。全空港が「SEE ATTACHED CHART」で、
    形状はチャート図にしか無い。ただし図の多くは **(1)(2)… の番号付き座標表**
    を持っていて、そこはテキスト層から機械抽出できる(→ tools/aca_points.json)。
    区画の**繋ぎ方(どの番号をどの順で結ぶか)は図を見ないと分からない**ので、
    座標は自動・構成は手書き、という gen_tra.py と同じ作りにしてある。

  ⚠ **検算を必ず通すこと**。副区画の球面面積の合計が外形と一致しなければ
    読み違えている。横田ACAでは (17)(18)(19) の三角形を取りこぼしていて
    0.3%ずれ、8000区画が (19)→(17)→(18) と回ると分かって0.0000%になった。

  ⚠ 高度の読み方: ラベルは「上の線 / 上限 / 下限 / 下の線」。
    東京ACAの「FL240 / 4000 (EXC 4000)」は上限FL240・下限4000(4000は含まない)。
    **横田ACAのように数値が1つで下線が無い図は上限のみ**で、下限は図に無い。
    無い下限を勝手に GND と決めないこと(lo=None のまま出して注記する)。

出力: aca.json {"eff":..,"f":[{n,jp,k,icao,up,lo,exc,pts},..]}
  k … 'ACA'=進入管制区 / 'TCA'=ターミナルコントロールエリア
使い方: python3 tools/gen_aca.py
"""
import re, os, sys, glob, json, math, subprocess

PT = re.compile(r'\((\d{1,3})\)\s*(\d{6}(?:\.\d+)?)N\s*/?\s*(\d{7}(?:\.\d+)?)E')
R_EARTH = 6371.0088


def dms(la, lo):
    return (round(int(la[0:2]) + int(la[2:4])/60 + float(la[4:])/3600, 6),
            round(int(lo[0:3]) + int(lo[3:5])/60 + float(lo[5:])/3600, 6))


def sph_area(pts):
    """球面上の面積(km²)。**平面近似だと緯度幅の広い外形で誤差が出る**
       (横田で72km²=0.3%ずれた)。検算に使うのでここは近似しない"""
    s = 0.0
    for i in range(len(pts)):
        la1, lo1 = map(math.radians, pts[i])
        la2, lo2 = map(math.radians, pts[(i+1) % len(pts)])
        s += (lo2 - lo1) * (2 + math.sin(la1) + math.sin(la2))
    return abs(s) * R_EARTH * R_EARTH / 2


def ad2_dir():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine'):
        d = sorted(glob.glob(os.path.expanduser(pat)))
        if d: return d[-1]
    return None


def harvest(base):
    """全AD2から ACA/TCA チャートの番号付き座標表を集める"""
    out = {}
    for pdf in sorted(glob.glob(os.path.join(base, '*.pdf'))):
        icao = os.path.basename(pdf).split('__')[0]
        t = subprocess.run(['pdftotext', '-layout', pdf, '-'],
                           capture_output=True, text=True).stdout
        for pg in t.split('\f'):
            head = pg[:900]
            k = ('TCA' if 'Terminal Control Area' in head else
                 'ACA' if 'Approach Control Area' in head else None)
            if not k: continue
            pts = PT.findall(pg)
            if not pts: continue
            d = {int(n): dms(a, b) for n, a, b in pts}
            key = icao + '/' + k
            # 同じ図が複数ページに割れることがあるのでマージする
            out.setdefault(key, {}).update(d)
    return out


# ── 図を見て起こした区画構成 ───────────────────────────────────────
# ring は座標表の番号を結ぶ順。up/lo は ft(FLxxx は 100倍して入れる)。
# exc=True は「下限の高度自体は含まない(EXC)」の意。
SPEC = {
 'RJTY/ACA': dict(
   jp='横田進入管制区', n='YOKOTA ACA', eff_note='図に下限の記載なし',
   outer=[1,2,3,4,5,10,11,12,17,19,20,21,22,9,6],
   sub=[
     dict(n='FL230', up=23000, ring=[1,2,3,4,5,6]),
     dict(n='FL180', up=18000, ring=[5,6,9,8,7]),
     dict(n='FL160', up=16000, ring=[5,7,13,14,12,11,10]),
     dict(n='12000', up=12000, ring=[7,8,16,15,14,13]),
     # ⚠ (19)→(17)→(18) と回る。(17)を飛ばすと三角形(17)(18)(19)が抜ける
     dict(n='8000',  up=8000,  ring=[8,9,22,21,20,19,17,18,15,16]),
     dict(n='FL140', up=14000, ring=[14,15,18,17,12]),
   ]),
}


def main():
    base = ad2_dir()
    if not base: print('AIPのAD2フォルダが見つかりません', file=sys.stderr); sys.exit(1)
    here = os.path.dirname(os.path.abspath(__file__))
    cache = os.path.join(here, 'aca_points.json')
    if '--cache' in sys.argv and os.path.exists(cache):
        P = json.load(open(cache))
    else:
        print('AD2のチャートから座標表を抽出中…')
        P = harvest(base)
        json.dump(P, open(cache, 'w'), ensure_ascii=False, indent=0, sort_keys=True)
    print(f'  {len(P)} チャート / {sum(len(v) for v in P.values())} 点 → tools/aca_points.json')
    for k in sorted(P): print(f'    {k:12}{len(P[k]):4}点')

    out, ng = [], 0
    for key, sp in SPEC.items():
        pts = {int(a): b for a, b in P.get(key, {}).items()}
        if not pts: print(f'  ⚠ {key} の座標表が無い', file=sys.stderr); ng += 1; continue
        ring = lambda r: [list(pts[i]) for i in r]
        oa = sph_area(ring(sp['outer']))
        tot = sum(sph_area(ring(s['ring'])) for s in sp['sub'])
        d = abs(tot - oa) / oa * 100
        print(f"  {key}: 副区画{len(sp['sub'])} 合計{tot:.1f} / 外形{oa:.1f} km² 差{d:.4f}%")
        if d > 0.01:
            print(f'  ⚠ {key} は区画の読み違い(合計が外形と一致しない)', file=sys.stderr)
            ng += 1; continue
        icao, kind = key.split('/')
        for s in sp['sub']:
            out.append(dict(n=sp['n'] + ' ' + s['n'], jp=sp['jp'], k=kind, icao=icao,
                            up=s['up'], lo=s.get('lo'), rmk=sp.get('eff_note', ''),
                            pts=ring(s['ring'])))
    if ng: print(f'{ng} 件を検算落ちで除外', file=sys.stderr)

    dst = os.path.join(here, '..', 'aca.json')
    eff = os.path.basename(os.path.dirname(base))
    json.dump({'eff': eff, 'src': 'AIP Japan AD 2.17 添付チャート', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 区画 → aca.json ({os.path.getsize(dst)/1024:.0f}KB) AIRAC:{eff}')


if __name__ == '__main__': main()
