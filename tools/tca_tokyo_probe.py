#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東京TCA チャート読み取りの下ごしらえ (RJTT AD 2.17 添付図)
==========================================================
⚠ **これはまだ空域を出す生成器ではない**。図から区画を切り出すところまでの道具。
   aca.json には何も足さない。仕上げは BACKLOG の「東京TCA」を参照。

なぜ道具が要るか
----------------
他のACA図は (1)(2)… の番号付き座標表を持つのでジオリファレンス不要だが、
**東京TCAの図だけは座標が5点しか無い**。形は「30NM FM RJTT ARP」のように
弧と方位線の**名前**で描かれている。よって図の読み取りが要る。

分かっていること(2026-09-01 時点)
--------------------------------
* 図に名前で書かれた幾何は**全部実在を確認済み**(重ねて一致):
  RJTT ARP 15NM/30NM・RJTT ARP 140° / RJAA ARP 10/20/25/30NM・RJAA ARP 120°/160° /
  RJAK ARP 5NM(=霞ヶ浦CTR) / RJTE ARP 12NM(=館山CTR)
* 内部境界の多くは**既に持っている空域そのもの**(東京/成田/下総/木更津/館山/霞ヶ浦CTR、
  東京PCA NR1/NR2、成田PCA)。ASP_POLY から引ける
* 印字されている座標も名前付きの弧に乗る:
  350815N/1395937E = RJTE 12.01NM / 351610N/1402826E = RJAA 30.08NM /
  353908N/1401502E = RJAA 9.45NM。
  ただし **350627N/1394058E はどの弧にも乗らない**(富津岬付近の実頂点)
* **上限は全区画 10000**。例外はハッチの3区画だけで、そこは2段
  (1800-2999 と 6001-10000 / 1801-2999 と 6001-10000 / 1801-1999 と 6001-10000)

この道具でできること
--------------------
1. ジオリファレンス
   ⚠ navaidのラベル位置(HUC/SYE/SHT/NRE/CVT/OJT/TET)でアフィンを当てると
     残差8pt(≒1.2NM)で**足りない**。図に描かれている**CTR円を画像から探して**
     平行移動を補正すると一致する(霞ヶ浦CTR 5NMが一番濃く出る)。
   ⚠ インク量の最大化でアフィン6パラメータを全部動かすと**かえって悪化する**
2. 太線だけの抽出 (MaxFilter(5)→MinFilter(5))
   海岸線・文字・破線の注記・枠が消えて、空域の線だけが残る
3. 塗り分け(scanline flood fill)で区画を切り出す → 36領域

⚠⚠ **ここで止まっている**: 成田南東の3本帯(10000/4001・5001・6001)のように
   **内部の分割線が細く、太線フィルタで消えて1区画に融合する**。
   MaxFilter(3)まで緩めると海岸線が残って偽の区画ができる。
   直線だけを拾う(Hough等)か、細線側を別に処理する必要がある。

使い方: python3 tools/tca_tokyo_probe.py   → /tmp に区画の色分け画像を出す
"""
import re, os, sys, glob, math, subprocess
import numpy as np

try:
    from PIL import Image, ImageFilter, ImageDraw
except ImportError:
    print('Pillow が要る', file=sys.stderr); sys.exit(1)

PAGE = 28          # RJTT AD2-28 = Tokyo Terminal Control Area
DPI = 300
# navaidのラベル位置(pt)。⚠ 記号そのものではなくラベルなので数pt ずれる
NAV = {'HUC': (36.18701, 140.41373), 'SYE': (36.01093, 139.83917),
       'SHT': (35.80194, 140.00972), 'NRE': (35.78234, 140.36254),
       'CVT': (35.72668, 140.79991), 'OJT': (35.18414, 140.37143),
       'TET': (34.97083, 139.83806)}
LBL = {'HUC': (287.7, 116.4), 'SYE': (154.0, 184.9), 'SHT': (176.3, 257.8),
       'NRE': (282.5, 271.3), 'CVT': (392.2, 276.4), 'OJT': (291.0, 454.1),
       'TET': (154.8, 545.8)}
# 描かれているCTR円で平行移動を補正した量(px @300dpi)。霞ヶ浦・成田の実測から
SHIFT = (42, 22)


def rjtt_pdf():
    for pat in ('~/Downloads/AIP File Download Service/1_AIP (PDF)/*/AD2_Combine/RJTT__*.pdf',
                '~/Downloads/1_AIP (PDF)/*/AD2_Combine/RJTT__*.pdf'):
        f = sorted(glob.glob(os.path.expanduser(pat)))
        if f: return f[-1]
    return None


def georef():
    S = DPI / 72.0
    ks = list(NAV)
    A = np.array([[NAV[k][1], NAV[k][0], 1] for k in ks])
    cx = np.linalg.lstsq(A, np.array([LBL[k][0]*S for k in ks]), rcond=None)[0]
    cy = np.linalg.lstsq(A, np.array([LBL[k][1]*S for k in ks]), rcond=None)[0]
    cx[2] += SHIFT[0]; cy[2] += SHIFT[1]
    return cx, cy


def thick_lines(img):
    """空域の線だけ残す。海岸線・文字・破線・枠は消える"""
    er = img.filter(ImageFilter.MaxFilter(5))        # 暗部を収縮
    return np.array(Image.fromarray(np.where(np.array(er) < 128, 0, 255).astype('uint8'))
                    .filter(ImageFilter.MinFilter(5))) < 128


def segment(line):
    """線で囲まれた領域を塗り分ける(scanline flood fill)"""
    H, W = line.shape
    lab = np.zeros((H, W), dtype=np.int32); lab[line] = -1

    def fill(sy, sx, val):
        st = [(sy, sx)]; n = 0
        while st:
            y, x = st.pop()
            if lab[y, x] != 0: continue
            x0 = x
            while x0 > 0 and lab[y, x0-1] == 0: x0 -= 1
            x1 = x
            while x1 < W-1 and lab[y, x1+1] == 0: x1 += 1
            lab[y, x0:x1+1] = val; n += x1-x0+1
            for yy in (y-1, y+1):
                if not (0 <= yy < H): continue
                idx = np.where(lab[yy, x0:x1+1] == 0)[0]
                if not len(idx): continue
                br = np.where(np.diff(idx) > 1)[0]
                for s in [idx[0]] + [idx[i+1] for i in br]:
                    st.append((yy, x0+int(s)))
        return n

    fill(3, 3, -2)                                   # 外側
    cells, cid = [], 1
    while True:
        ys, xs = np.where(lab == 0)
        if not len(ys): break
        n = fill(int(ys[0]), int(xs[0]), cid)
        cells.append((cid, int(xs[0]), int(ys[0]), n)); cid += 1
        if cid > 400: break
    return lab, cells


def main():
    pdf = rjtt_pdf()
    if not pdf: print('RJTTのPDFが見つからない', file=sys.stderr); sys.exit(1)
    subprocess.run(['pdftoppm', '-png', '-r', str(DPI), '-f', str(PAGE), '-l', str(PAGE),
                    pdf, '/tmp/tca_tt'], check=True)
    png = sorted(glob.glob('/tmp/tca_tt-*.png'))[-1]
    img = Image.open(png).convert('L')
    line = thick_lines(img)
    lab, cells = segment(line)
    big = [c for c in cells if c[3] >= 800]
    print(f'  区画 {len(big)} 個(800px以上) / 全{len(cells)}')
    rng = np.random.default_rng(7)
    arr = np.full(img.size[::-1] + (3,), 255, dtype=np.uint8)
    for cid, _, _, n in big:
        if n >= 800: arr[lab == cid] = rng.integers(120, 255, 3)
    out = Image.blend(Image.open(png).convert('RGB'), Image.fromarray(arr), 0.55)
    d = ImageDraw.Draw(out)
    for cid, _, _, n in big:
        ys, xs = np.where(lab == cid)
        d.text((int(xs.mean()), int(ys.mean())), str(cid), fill=(200, 0, 0))
    out.save('/tmp/tca_tokyo_cells.png')
    print('  → /tmp/tca_tokyo_cells.png')
    cx, cy = georef()
    print(f'  ジオリファレンス: 経度1°={cx[0]:.1f}px 緯度1°={cy[1]:.1f}px')


if __name__ == '__main__':
    main()
