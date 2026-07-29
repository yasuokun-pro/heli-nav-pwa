#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原子力施設(飛行回避)レイヤー 生成 (nuke.json)
==============================================
出典: AIP Japan **ENR 5.3.2.4 原子力施設 / Nuclear facilities**

  「航空機による原子力施設に対する災害を防止するため、
    下記の施設付近の上空の飛行は、できる限り避けること。」

AIPで「上空の飛行を避けること」と明記されているのはここだけ(ENR 5.6 鳥の渡りはNil)。
禁止空域ではないので進入しても違反ではないが、回避が求められている区域。
各施設は多角形の頂点(DMS)で定義されている。

★印の施設には黄色の閃光式灯火(10万カンデラ・毎分40〜60回)が設置されている。
  夜間・薄暮の位置確認に使えるので lit フラグとして持つ。

出力: nuke.json {"eff":"AIPの発効日","f":[{n,en,adr,ty,lit,pts:[[lat,lng],...]},...]}
使い方: python3 tools/gen_nuke.py
AIRAC更新時は再実行して差分を確認する(施設の追加・廃止がある)。
"""
import re, os, sys, glob, subprocess, json

SEC_START = '2.4. 原子力施設'
SEC_END = 'ENR 5.4 航法上の障害物'


def dms(s):
    """354826N1401749E → (35.8072, 140.2969)"""
    m = re.match(r'(\d{2})(\d{2})(\d{2})N(\d{3})(\d{2})(\d{2})E', s)
    la = int(m.group(1)) + int(m.group(2)) / 60 + int(m.group(3)) / 3600
    lo = int(m.group(4)) + int(m.group(5)) / 60 + int(m.group(6)) / 3600
    return [round(la, 5), round(lo, 5)]


def latest_enr():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/ENR_*.pdf',
                '~/Downloads/1_AIP (PDF)/*/ENR_*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: return f[-1]
    return None


def main():
    pdf = latest_enr()
    if not pdf:
        print('ENRのPDFが見つかりません', file=sys.stderr); sys.exit(1)
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'],
                         capture_output=True, text=True).stdout
    seg = txt[txt.index(SEC_START):txt.index(SEC_END, txt.index(SEC_START))]
    eff = (re.search(r'EFF:\s*(\d+\s+\w+\s+\d{4})', seg) or [None, ''])[1]

    # pdftotext -layout の出力は段組。「(1)」で座標の並びが始まるので、
    # その直前までに溜めた行をその施設のヘッダ(和名/英名/住所/種類)として読む
    NOISE = re.compile(r'AIP Japan|^ENR 5\.|Civil Aviation|DESIGNATION|FACILITY TYPE|'
                       r'Coordinates|following points|^場所|^名称|^施設の種類|^\d+/\d+/\d+$|'
                       r'^2\.4|Nuclear facilities|閃光|カンデラ|星印|Asterisk|flashing')

    def parse_head(lines):
        # 章の前書き(本文)が混ざらないよう、直前の数行だけを見る。
        # 施設名の行は「。」を含まない短い行なので、それで本文を落とす
        lines = [l for l in lines if l.strip() and '。' not in l and 'shall avoid' not in l][-6:]
        f = {'n': '', 'en': '', 'adr': '', 'ty': '', 'lit': 0, 'pts': []}
        for ln in lines:
            s = ln.rstrip()
            if not s.strip() or NOISE.search(s.strip()): continue
            if s.lstrip().startswith('*'):
                f['lit'] = 1
                s = s.replace('*', ' ', 1)
            # 段組は2スペース以上で区切られている
            cols = [c.strip() for c in re.split(r'\s{2,}', s.strip()) if c.strip()]
            if not cols: continue
            head = cols[0]
            jp = bool(re.search(r'[^\x00-\x7F]', head))
            if jp: f['n'] += head
            else:  f['en'] = (f['en'] + ' ' + head).strip()
            for c in cols[1:]:
                if re.search(r'[都道府県]', c) or re.search(r'-shi|-cho|-mura|-gun|\bin\b', c):
                    if not f['adr']: f['adr'] = c
                elif not f['ty']: f['ty'] = c
        return f

    facs, buf, cur = [], [], None
    for ln in seg.split('\n'):
        c = re.search(r'\((\d+)\)\s*(\d{6}N\d{7}E)', ln)
        if not c:
            buf.append(ln)
            continue
        if int(c.group(1)) == 1:
            cur = parse_head(buf); facs.append(cur)
        buf = []
        if cur is None: continue
        cur['pts'].append(dms(c.group(2)))
        # 座標行の右側に施設種類が続くことがある(再処理事業所など複数種類)
        tail = ln[c.end():].strip()
        if tail and not re.match(r'^[\d()]+$', tail) and not NOISE.search(tail):
            cur['ty'] = (cur['ty'] + ' / ' + ' '.join(tail.split())).strip(' /')

    out = []
    for f in facs:
        f.pop('_head', None)
        if len(f['pts']) < 3: continue               # 座標が揃わないものは捨てる
        # pdftotextが入れる字間の空白を詰める。段組がずれて英語の住所が
        # 和名にくっつくことがある(もんじゅ等)ので、和名からASCIIを落とす
        f['n'] = re.sub(r'[\x00-\x7F]+', '', f['n']).strip()
        # 施設種類は和英が交互に入るので和文だけ残す
        f['ty'] = ' / '.join(dict.fromkeys(
            re.sub(r'\s+', '', t) for t in f['ty'].split(' / ')
            if re.search(r'[^\x00-\x7F]', t)))
        out.append(f)

    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(here, '..', 'nuke.json')
    json.dump({'eff': eff, 'src': 'AIP Japan ENR 5.3.2.4', 'f': out},
              open(dst, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(out)} 施設 → nuke.json ({os.path.getsize(dst)/1024:.0f}KB) EFF:{eff}')
    print(f'  灯火あり(★): {sum(f["lit"] for f in out)}')
    for f in out[:5]:
        print(f'  {"★" if f["lit"] else " "} {f["n"]} [{f["ty"]}] {len(f["pts"])}点')


if __name__ == '__main__': main()
