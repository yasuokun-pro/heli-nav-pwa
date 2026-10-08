#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ILS の最終進入経路 生成 (ils.json)
==================================
出典: AIP Japan 各飛行場 **AD 2.19**(ILS-LOC / ILS-GP のアンテナ位置・GP 角・ILS 参照高 RDH)と
**AD 2.12**(滑走路の真方位・THR 標高)。

なぜ要るか(ユーザー要望 2026-10-08): 厚木の南の海岸線のように、ILS の最終進入経路の**下をくぐって**飛ぶ・
**高度で避ける**場所がある。地図に進入経路と「THR から何NMで GP 上は何ft」を出す。

作り方:
  ・進入コース = **LOC アンテナを通る、滑走路の真方位の直線**(LOC は向こう側の末端の先の中心線上にある)
  ・GP の起点 = GP アンテナをその直線に下ろした点。THR はそこから RDH/tan(GP角) だけ手前
    (例: 羽田 16L は RDH 53ft・3.0° で 308m。AIP の「GP: 312m inside FM THR」と合う)
  ・GP 上の高さ(ft MSL) = THR 標高 + RDH + d(NM)×6076×tan(GP角)  … アプリが距離ごとに出す
  ・検算: GP アンテナは中心線から 100〜160m 横にある。60〜250m を外れたら向きを疑って警告
滑走路の真方位が AD 2.12 に無いとき(横田など):
  ① 反対向きの ILS の LOC アンテナどうしを結ぶ(両方とも中心線上)  ② 備考の BRG(MAG) + 磁気偏差(AD 2.2)
⚠ LDA(オフセットの LOC)は含めない。GP の無い LOC 単独は ang=null(高さは出さず線だけ)

出力: {eff, src, ils:[{icao, rwy, id, f, ang, rdh, elev, crs(真方位・進入機の向き), thr:[lat,lng], loc:[lat,lng], gpOff(m)}]}
使い方: python3 tools/gen_ils.py
"""
import os, re, json, glob, subprocess, math

HERE = os.path.dirname(os.path.abspath(__file__))
AIP_ROOT = os.path.normpath(os.path.join(HERE, '..', 'aip'))   # ⚠ .gitignore 済み・公開リポジトリには入れない
LAT = re.compile(r'(\d{6}(?:\.\d+)?)\s*N')
LON = re.compile(r'(1\d{6}(?:\.\d+)?)\s*E')
FREQ = re.compile(r'(\d{3}\.\d{1,2})\s*MHz')
AID = re.compile(r'^\s*(ILS[-/ ]?LOC|LOC|ILS[-/ ]?GP|GP|LDA[-/ ]?LOC|LDA|ILS[-/ ]?DME|DME|IM|MM|OM|TACAN|VOR|NDB|L)\s*(\d{2}[LRC]?)?\b')
R_NM = 3440.065


def pdfs():
    f = sorted(glob.glob(AIP_ROOT + '/1_AIP (PDF)/*/AD2_Combine/*.pdf'))
    if not f: return [], ''
    latest = max(os.path.basename(os.path.dirname(os.path.dirname(x))) for x in f)
    return [x for x in f if os.path.basename(os.path.dirname(os.path.dirname(x))) == latest], latest


def dms(v, is_lon):
    d = 3 if is_lon else 2
    return int(v[:d]) + int(v[d:d+2]) / 60 + float(v[d+2:]) / 3600


def section(L, a, b):
    on, out = False, []
    for l in L:
        if re.search(r'AD 2\.%s\b' % a, l): on = True
        elif on and re.search(r'AD 2\.%s\b' % b, l): break
        if on: out.append(l)
    return out


def runways(L):
    """AD 2.12: {RWY: (真方位 or None, THR標高 or None)}"""
    S = section(L, '12', '13')
    out = {}
    for k, l in enumerate(S):
        m = re.match(r'^\s{0,20}(\d{2}[LRC]?)\s+(\d{3}(?:\.\d+)?)\s*°', l) or re.match(r'^\s{0,20}(\d{2}[LRC]?)\s{2,}', l)
        if not m or not (1 <= int(m.group(1)[:2]) <= 36) or m.group(1) in out: continue
        brg = float(m.group(2)) if m.lastindex and m.lastindex >= 2 else None
        el = None
        for w in S[max(0, k - 3):k + 4]:
            me = re.search(r'THR(?:\s*ELEV(?:ATION)?)?\s*[:：]?\s*(-?\d+(?:\.\d+)?)\s*(?:ft|FT)', w)
            if me: el = float(me.group(1)); break
        out[m.group(1)] = (brg, el)
    return out


def magvar(L):
    """磁気偏差(西偏を正)。AD 2.2 が Nil の飛行場もあるので文書全体の "VAR 7˚W" を見る。
    ⚠ 度の記号が ° ではなく ˚(U+02DA)のことがある(下総)"""
    for l in L:
        m = re.search(r'VAR[^0-9]{0,12}(\d+(?:\.\d+)?)\s*[°˚º]\s*([EW])', l, re.I)
        if m: return float(m.group(1)) * (1 if m.group(2).upper() == 'W' else -1)
    return None


def aids(L):
    """AD 2.19 を施設ごとの塊に分ける: [{t, rwy, head, txt, lat, lng}]"""
    S = section(L, '19', '20')
    blocks, cur = [], None
    for l in S:
        m = AID.match(l)
        if m and (LAT.search(l) or FREQ.search(l) or re.search(r'MHz|kHz', l)):
            cur = {'t': re.sub(r'[-/ ]', '-', m.group(1)).upper(), 'rwy': m.group(2) or '', 'head': l, 'lines': [l]}
            blocks.append(cur)
        elif cur is not None:
            cur['lines'].append(l)
    for b in blocks:
        b['txt'] = re.sub(r'\s+', ' ', ' '.join(b['lines']))   # ⚠ 段組の空白を詰めないと「datum   16.3m」が当たらない
        la = LAT.search(b['txt']); lo = LON.search(b['txt'])
        b['pos'] = (dms(la.group(1), False), dms(lo.group(1), True)) if la and lo else None
    return blocks


def dest(p, brg, d):
    la, lo, b, a = math.radians(p[0]), math.radians(p[1]), math.radians(brg), d / R_NM
    la2 = math.asin(math.sin(la) * math.cos(a) + math.cos(la) * math.sin(a) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(a) * math.cos(la), math.cos(a) - math.sin(la) * math.sin(la2))
    return (math.degrees(la2), math.degrees(lo2))


def brg_of(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def local(o, p):
    """o を原点にした m 単位の平面座標(東, 北)"""
    return ((p[1] - o[1]) * 111320 * math.cos(math.radians(o[0])), (p[0] - o[0]) * 110540)


def recip(r):
    n = (int(r[:2]) + 17) % 36 + 1
    return '%02d' % n + {'L': 'R', 'R': 'L', 'C': 'C'}.get(r[2:], '')


def main():
    files, eff = pdfs()
    AD = {a['icao']: a for a in json.load(open(os.path.join(HERE, '..', 'ad.json')))['f']}
    out, warn, seen = [], [], set()
    for pdf in files:
        icao = os.path.basename(pdf)[:4]
        txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
        if 'LOC' not in txt: continue
        L = txt.split('\n')
        RW, B, var = runways(L), aids(L), magvar(L)
        locs = {b['rwy']: b for b in B if b['t'] in ('ILS-LOC', 'LOC') and b['rwy'] and b['pos']}
        gps = {b['rwy']: b for b in B if b['t'] in ('ILS-GP', 'GP') and b['rwy'] and b['pos']}
        for rwy, lb in locs.items():
            if (icao, rwy) in seen: continue
            seen.add((icao, rwy))
            # 進入コース(真方位)
            crs, how = (RW.get(rwy) or (None, None))[0], 'AD 2.12'
            if crs is None and recip(rwy) in locs:
                crs, how = brg_of(locs[recip(rwy)]['pos'], lb['pos']), '両端の LOC'
            if crs is None and var is not None:
                mm = re.search(r'BRG\s*\(?\s*MAG\s*\)?\s*(\d{3}(?:\.\d+)?)|BRG\s*(\d{3}(?:\.\d+)?)\s*°?\s*\(\s*MAG', lb['txt'])
                if mm: crs, how = (float(mm.group(1) or mm.group(2)) - var) % 360, '備考の磁方位+偏差'
            if crs is None: warn.append(f'{icao} {rwy}: 進入コースの向きが分からない'); continue
            gb = gps.get(rwy)
            T = gb['txt'] if gb else lb['txt']
            ma = re.search(r'(?:GP\s*)?angle[^0-9]{0,6}(\d\.\d{1,2})\s*°', T, re.I) or re.search(r'\b([23]\.\d{1,2})\s*°', T)
            mr = re.search(r'datum[^0-9]{0,24}(\d+(?:\.\d+)?)\s*m\s*\(\s*(\d+(?:\.\d+)?)\s*ft\s*\)', T, re.I) or \
                 re.search(r'(?:RDH|TCH)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*(ft)', T, re.I)
            ang = float(ma.group(1)) if (gb and ma) else None
            rdh = (round(float(mr.group(2))) if mr.group(2) != 'ft' else round(float(mr.group(1)))) if mr else None
            elev = (RW.get(rwy) or (None, None))[1]
            elev_src = 'THR'
            if elev is None and icao in AD: elev, elev_src = AD[icao].get('elev'), '飛行場標高'
            # THR の位置: GP アンテナを中心線に下ろした点から RDH/tan だけ手前。GP が無ければ LOC から滑走路長は分からないので LOC を基準に出さない
            loc = lb['pos']
            if gb:
                e, n = local(loc, gb['pos'])
                ux, uy = math.sin(math.radians(crs)), math.cos(math.radians(crs))   # 進入機の向き(THR→LOC)
                along = e * ux + n * uy            # LOC から見て GP は手前(負)
                off = abs(e * uy - n * ux)
                if not (60 <= off <= 250):
                    # LOC が中心線上に無い(オフセット)か向きの取り違え。間違った線を引くより出さない
                    warn.append(f'{icao} {rwy}: GP の横ずれ {off:.0f}m(向き {crs:.1f}° {how})→ 出さない'); continue
                foot = dest(loc, crs, along / 1852)                                  # 中心線上の GP の足
                setb = (rdh or 50) / math.tan(math.radians(ang or 3.0)) * 0.3048    # m
                thr = dest(foot, (crs + 180) % 360, setb / 1852)
            else:
                thr, off = None, None
                warn.append(f'{icao} {rwy}: GP なし(LOC 単独)。線を引く起点が無いので出さない'); continue
            if ang is None: warn.append(f'{icao} {rwy}: GP 角が読めない(3.0°で計算)')
            if rdh is None: warn.append(f'{icao} {rwy}: RDH が読めない(50ft で計算)')
            if elev_src != 'THR': warn.append(f'{icao} {rwy}: THR 標高が無いので飛行場標高 {elev}ft')
            mid = re.search(r'\b(I-?[A-Z]{2,3})\b', lb['head'][len(AID.match(lb['head']).group(0)):])
            mf = FREQ.search(lb['txt'])
            out.append({'icao': icao, 'rwy': rwy, 'id': mid.group(1) if mid else '', 'f': mf.group(1) + 'MHz' if mf else '',
                        'ang': ang or 3.0, 'angAs': 0 if ang else 1, 'rdh': rdh or 50, 'rdhAs': 0 if rdh else 1,
                        'elev': elev, 'elevAd': 1 if elev_src != 'THR' else 0, 'crs': round(crs, 2), 'crsBy': how,
                        'thr': [round(thr[0], 6), round(thr[1], 6)], 'loc': [round(loc[0], 6), round(loc[1], 6)],
                        'gpOff': round(off) if off is not None else None})
    json.dump({'eff': eff, 'src': 'AIP AD 2.12 / AD 2.19', 'ils': out},
              open(os.path.join(HERE, '..', 'ils.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} ILS / {len(set(o["icao"] for o in out))} 飛行場 → ils.json')
    for w in warn: print('  ⚠', w)


if __name__ == '__main__':
    main()
