#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIXM の差分(AIXM_DIFF_*)を全件(AIXM_ALL_*)に当てる
======================================================
SWIM の AIP データ配信は、初回に全件(AIXM_ALL_<日時>・約840MB)、以後は AIP の発行ごとに差分(AIXM_DIFF_<日時>)を送ってくる。
差分の中身(2026-10-14 の初回の差分で確認):
  ・変わった地物(gml:identifier ごと)だけが入っている
  ・その地物は**全部の時間スライスを持ち直している**。BASELINE が版ごとに全部あり、前の BASELINE の終わり(endPosition)も
    「unknown」から新しい版の発効日に書き換わっている。PERMDELTA は BASELINE と同じ番号で並んでいる
  → 差分の地物で全件の同じ地物を**丸ごと置き換え**、全件に無い地物は足せばよい。プロパティ単位で継ぎ足す必要はない
    (念のため、全件にあった版の番号(sequenceNumber)が差分で欠けていたら警告する)

出力: aip/aixm_dist/AIXM_ALL_<最後に当てた差分の日時>.xml と、その来歴 .applied.json
      生成器は sorted(glob('AIXM_ALL_*.xml'))[-1] を読むので、そのまま差分込みの版が使われる
      ⚠ aip/ は .gitignore 済み。SWIM のデータを公開リポジトリに置かない
差分の zip は VM から持ってきたまま aip/aixm_dist/ に置けばよい(中の AIXM_*.xml を取り出す。VM 上の zip 名は受信時刻)

使い方: python3 -I tools/aixm_apply_diff.py [--dry]   --dry … 当てる内容の一覧だけ出して書かない
"""
import os, sys, re, glob, json, zipfile, collections
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.normpath(os.path.join(HERE, '..', 'aip', 'aixm_dist'))
A = '{http://www.aixm.aero/schema/5.1.1}'
G = '{http://www.opengis.net/gml/3.2}'
OPEN, CLOSE = b'<message:hasMember>', b'</message:hasMember>'
RE_ID = re.compile(rb'<gml:identifier[^>]*>([^<]+)</gml:identifier>')
NS = ('xmlns:message="http://www.aixm.aero/schema/5.1.1/message" xmlns:xlink="http://www.w3.org/1999/xlink" '
      'xmlns:aixm="http://www.aixm.aero/schema/5.1.1" xmlns:gml="http://www.opengis.net/gml/3.2" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')


def stamp(p):
    return re.search(r'_(\d{14})', os.path.basename(p)).group(1)


def unzip_new():
    """aixm_dist の zip から、まだ取り出していない AIXM_ALL/AIXM_DIFF の xml を取り出す"""
    for z in glob.glob(os.path.join(DIR, '*.zip')):
        try:
            zf = zipfile.ZipFile(z)
        except zipfile.BadZipFile:
            continue
        for i in zf.infolist():
            n, b = i.filename, os.path.basename(i.filename)
            if i.flag_bits & 1:  # SWIM のダウンロードに入っている全件はパスワード付き(SD 利用者限定)。VM で受けたもので足りる
                continue
            if re.match(r'AIXM_(ALL|DIFF)_\d{14}\.xml$', b) and not os.path.exists(os.path.join(DIR, b)):
                print('取り出し', os.path.basename(z), '→', b)
                with zf.open(n) as s, open(os.path.join(DIR, b), 'wb') as d:
                    while True:
                        c = s.read(1 << 22)
                        if not c: break
                        d.write(c)


def blocks(path):
    """('head', bytes) → ('m', id, bytes)… → ('tail', bytes)。hasMember は行頭から1行で開閉している(全件・差分とも)"""
    head, buf, inm = [], [], False
    with open(path, 'rb') as f:
        for line in f:
            s = line.strip()
            if not inm:
                if s == OPEN:
                    if head is not None:
                        yield ('head', b''.join(head)); head = None
                    inm, buf = True, [line]
                elif head is not None:
                    head.append(line)
                else:
                    buf.append(line)  # 最後の hasMember の後ろ(閉じタグ)
            else:
                buf.append(line)
                if s == CLOSE:
                    b = b''.join(buf)
                    m = RE_ID.search(b)
                    yield ('m', m.group(1).decode().strip() if m else None, b)
                    inm, buf = False, []
    yield ('tail', b''.join(buf))


def info(b):
    """地物の種類・名前・時間スライス(版番号・解釈・始まり・終わり)"""
    f = ET.fromstring(b'<r ' + NS.encode() + b'>' + b + b'</r>')[0][0]
    t = f.tag.replace(A, '')
    sl, name = [], None
    for ts in f.iter():
        if not ts.tag.endswith('TimeSlice') or ts.find(A + 'interpretation') is None: continue
        e = ts.find('.//' + G + 'endPosition')
        sl.append({'interp': ts.findtext(A + 'interpretation'), 'seq': ts.findtext(A + 'sequenceNumber'),
                   'corr': ts.findtext(A + 'correctionNumber'), 'begin': ts.findtext('.//' + G + 'beginPosition'),
                   'end': (e.text or e.get('indeterminatePosition')) if e is not None else None})
        if ts.findtext(A + 'interpretation') == 'BASELINE':
            for k in ('designator', 'name', 'locationIndicatorICAO'):
                v = ts.findtext(A + k)
                if v: name = v; break
    return t, name, sl


def main():
    dry = '--dry' in sys.argv
    unzip_new()
    alls = sorted(glob.glob(os.path.join(DIR, 'AIXM_ALL_*.xml')), key=stamp)
    if not alls: sys.exit('AIXM_ALL_*.xml がありません')
    base = alls[-1]
    diffs = sorted((p for p in glob.glob(os.path.join(DIR, 'AIXM_DIFF_*.xml')) if stamp(p) > stamp(base)), key=stamp)
    if not diffs:
        print('当てる差分はありません(最新', os.path.basename(base), ')'); return

    # 差分を古い順に重ねる(同じ地物は後の差分が勝つ)
    new = collections.OrderedDict()
    for d in diffs:
        n = 0
        for k, gid, b in ((x[0], x[1] if x[0] == 'm' else None, x[-1]) for x in blocks(d)):
            if k == 'm': new[gid] = b; n += 1
        print('差分', os.path.basename(d), n, '地物')

    out = os.path.join(DIR, 'AIXM_ALL_%s.xml' % stamp(diffs[-1]))
    tmp = out + '.part'
    w = None if dry else open(tmp, 'wb')
    seen, rep, cnt = set(), [], collections.Counter()
    for x in blocks(base):
        if x[0] == 'm':
            gid, b = x[1], x[2]
            if gid in new:
                t, name, old = info(b)
                t2, name2, sl = info(new[gid])
                lost = {s['seq'] for s in old} - {s['seq'] for s in sl}
                fresh = [s for s in sl if s['interp'] == 'BASELINE' and (s['seq'], s['corr']) not in {(o['seq'], o['corr']) for o in old if o['interp'] == 'BASELINE'}]
                rep.append({'id': gid, 'type': t2, 'name': name2 or name, 'op': '置換',
                            'new': [(s['seq'], s['corr'], s['begin'], s['end']) for s in fresh], 'lost': sorted(lost)})
                cnt[(t2, '置換')] += 1
                seen.add(gid); b = new[gid]
            if w: w.write(b)
        elif x[0] == 'head':
            if w: w.write(x[1])
        else:
            for gid, b in new.items():
                if gid in seen: continue
                t, name, sl = info(b)
                rep.append({'id': gid, 'type': t, 'name': name, 'op': '追加',
                            'new': [(s['seq'], s['corr'], s['begin'], s['end']) for s in sl if s['interp'] == 'BASELINE'], 'lost': []})
                cnt[(t, '追加')] += 1
                if w: w.write(b)
            if w: w.write(x[1])

    for (t, op), n in sorted(cnt.items()): print('  %-22s %s %d' % (t, op, n))
    for r in sorted(rep, key=lambda r: (r['type'], r['name'] or '')):
        eff = sorted({s[2][:10] for s in r['new'] if s[2]})
        print('  %s %-20s %-24s 新しい版の発効 %s%s' % (r['op'], r['type'], (r['name'] or r['id'][:8])[:24], ','.join(eff) or '-',
                                                     '  ⚠ 版が欠けた ' + ','.join(r['lost']) if r['lost'] else ''))
    if w:
        w.close(); os.replace(tmp, out)
        json.dump({'base': os.path.basename(base), 'diffs': [os.path.basename(d) for d in diffs], 'changes': rep},
                  open(out[:-4] + '.applied.json', 'w'), ensure_ascii=False, indent=1)
        print('→', os.path.basename(out), os.path.getsize(out), 'bytes')


if __name__ == '__main__':
    main()
