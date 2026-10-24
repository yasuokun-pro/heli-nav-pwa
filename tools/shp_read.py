"""最小限のシェープファイル読み取り(pyshp を入れずに済ませるため)。
航空情報センターの「AIP に関する地図表示用データ」(aip/geo/<AIRAC>/Shapefile_<AIRAC>/)用。
点(1)・線(3)・面(5)とそれぞれの Z/M 版(11/13/15・21/23/25)の 2D 座標だけ読む。属性は .dbf(.cpg の文字コード)。

  from shp_read import read
  for geom, attrs in read('aip/geo/20261029/Shapefile_20261029/ACC_Sector_below_FL335_EFF20261029'):
      geom = {'type': 'Point'|'Line'|'Polygon', 'parts': [[(lng, lat), ...], ...]}
"""
import os
import struct


def _dbf(path, enc):
    with open(path, 'rb') as f:
        b = f.read()
    n, hlen, rlen = struct.unpack('<xxxxIHH', b[:12])
    fields, p = [], 32
    while b[p] != 0x0D:
        name = b[p:p + 11].split(b'\0')[0].decode('ascii', 'replace')
        typ, ln, dec = chr(b[p + 11]), b[p + 16], b[p + 17]
        fields.append((name, typ, ln, dec))
        p += 32
    out = []
    for i in range(n):
        r = b[hlen + i * rlen: hlen + (i + 1) * rlen]
        if r[:1] == b'*':          # 削除済み
            out.append(None)
            continue
        q, d = 1, {}
        for name, typ, ln, dec in fields:
            raw = r[q:q + ln]
            q += ln
            s = raw.decode(enc, 'replace').strip().strip('\0').strip()
            if typ in 'NF':
                try:
                    v = float(s) if s else None
                    d[name] = int(v) if v is not None and dec == 0 and v == int(v) else v
                except ValueError:
                    d[name] = s or None
            else:
                d[name] = s or None
        out.append(d)
    return out


def _shp(path):
    with open(path, 'rb') as f:
        b = f.read()
    p, out = 100, []
    while p < len(b):
        _, clen = struct.unpack('>ii', b[p:p + 8])
        rec = b[p + 8: p + 8 + clen * 2]
        p += 8 + clen * 2
        st = struct.unpack('<i', rec[:4])[0]
        base = st % 10
        if st == 0:
            out.append(None)
        elif base == 1:
            x, y = struct.unpack('<dd', rec[4:20])
            out.append({'type': 'Point', 'parts': [[(x, y)]]})
        elif base in (3, 5):
            nparts, npts = struct.unpack('<ii', rec[36:44])
            idx = list(struct.unpack('<%di' % nparts, rec[44:44 + 4 * nparts]))
            q = 44 + 4 * nparts
            pts = [struct.unpack('<dd', rec[q + 16 * i: q + 16 * i + 16]) for i in range(npts)]
            parts = [pts[idx[k]:(idx[k + 1] if k + 1 < nparts else npts)] for k in range(nparts)]
            out.append({'type': 'Line' if base == 3 else 'Polygon', 'parts': parts})
        else:
            raise ValueError('shape type %d は未対応' % st)
    return out


def read(stem):
    stem = stem[:-4] if stem.endswith(('.shp', '.dbf')) else stem
    enc = 'utf-8'
    if os.path.exists(stem + '.cpg'):
        enc = open(stem + '.cpg').read().strip().lower().replace('utf8', 'utf-8') or 'utf-8'
    geoms, attrs = _shp(stem + '.shp'), _dbf(stem + '.dbf', enc)
    return [(g, a) for g, a in zip(geoms, attrs) if g and a is not None]
