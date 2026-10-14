#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SWIM AIP データ配信サービスの受信プログラム(Oracle VM で常駐・systemd)
=====================================================================
SWIM の Pub/Sub は「アカウントごとの受信キュー」に溜まる(Apache Artemis)。ここから AMQP 1.0 で取り出して保存する。
  ・接続: amqps://amq.swim.mlit.go.jp:5671、SASL PLAIN(キュー接続用認証ID・パスワード)
  ・受信アドレス: "<受信キューID>::<受信キューID>"(SWIM 共通 API 仕様書のサンプル。「::」の前後に同じ ID)
  ・1時間無通信だとセッションを切られる → AMQP のハートビート(idle_timeout)を 60 秒で出す
  ・メッセージは XML(MassMessage)。ボディは AIXM 5.1.1 を zip 圧縮して BASE64(付録05-1/05-2)。最大約40MB(上限250MB)
保存先(AIPD_DIR、既定 /var/lib/aipdist):
  raw/<受信時刻UTC>.xml.gz   … 受け取ったそのまま(必ず残す。後で解き直せるように)
  zip/<受信時刻UTC>.zip      … ボディを BASE64 から戻したもの
  aixm/<受信時刻UTC>/        … zip を展開したもの
  status.json                … 最後の接続・受信の記録(件数・大きさ・エラー)
⚠ 保存してから accept する(保存前に落ちてもキューに残る)
⚠ 資格情報は /etc/aipdist/env(root・600)だけ。リポジトリ・チャットに書かない
"""
import os, sys, re, io, gzip, json, base64, zipfile, logging, datetime, traceback
from proton import SSLDomain
from proton.handlers import MessagingHandler
from proton.reactor import Container

URL = os.environ.get('AIPD_URL', 'amqps://amq.swim.mlit.go.jp:5671')
USER = os.environ.get('AIPD_USER', '')
PASS = os.environ.get('AIPD_PASS', '')
QUEUE = os.environ.get('AIPD_QUEUE', '')
DIR = os.environ.get('AIPD_DIR', '/var/lib/aipdist')
log = logging.getLogger('aipdist')


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def status(**kw):
    p = os.path.join(DIR, 'status.json')
    try: st = json.load(open(p))
    except Exception: st = {}
    st.update(kw)
    tmp = p + '.tmp'
    json.dump(st, open(tmp, 'w'), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def text_of(body):
    if isinstance(body, (bytes, bytearray, memoryview)): return bytes(body).decode('utf-8', 'replace')
    return str(body)


def decode(xml, stamp):
    """MassMessage のボディ(BASE64 の zip)を戻して展開する。形が想定と違っても raw は残っているので失敗は記録だけ"""
    head = {k: (re.search(r'<%s>([^<]*)</%s>' % (k, k), xml[:20000]) or [None, None])[1]
            for k in ('MsgDef', 'MsgKind', 'MsgProperty', 'Destination', 'XMLKind', 'DataSize', 'CompKind', 'SendDateTime')}
    # ボディ: 一番長い BASE64 の塊(タグ名に依らない)
    best = None
    for m in re.finditer(r'>([A-Za-z0-9+/=\r\n]{200,})<', xml):
        if best is None or len(m.group(1)) > len(best): best = m.group(1)
    info = {'head': head, 'b64': len(best) if best else 0}
    if not best: return info
    raw = base64.b64decode(re.sub(r'\s+', '', best))
    info['bytes'] = len(raw)
    if raw[:2] == b'PK':
        zp = os.path.join(DIR, 'zip', stamp + '.zip')
        open(zp, 'wb').write(raw)
        out = os.path.join(DIR, 'aixm', stamp)
        os.makedirs(out, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            z.extractall(out)
            info['files'] = [(i.filename, i.file_size) for i in z.infolist()][:50]
    else:
        open(os.path.join(DIR, 'zip', stamp + '.bin'), 'wb').write(raw)
        info['note'] = 'zip ではない(先頭 %r)' % raw[:8]
    return info


class Recv(MessagingHandler):
    def __init__(self):
        super().__init__(prefetch=1, auto_accept=False)

    def on_start(self, e):
        ssl = SSLDomain(SSLDomain.MODE_CLIENT)
        ssl.set_trusted_ca_db('/etc/ssl/certs/ca-certificates.crt')
        ssl.set_peer_authentication(SSLDomain.VERIFY_PEER_NAME)
        conn = e.container.connect(URL, user=USER, password=PASS, allowed_mechs='PLAIN',
                                   ssl_domain=ssl, idle_timeout=60, reconnect=False)
        e.container.create_receiver(conn, '%s::%s' % (QUEUE, QUEUE))
        log.info('connecting %s queue=%s', URL, QUEUE)

    def on_link_opened(self, e):
        if e.receiver:
            log.info('receiver open')
            status(connected=now().isoformat(), error=None)

    def on_message(self, e):
        t = now()
        stamp = t.strftime('%Y%m%dT%H%M%S%fZ')[:-4] + 'Z'
        xml = text_of(e.message.body)
        rp = os.path.join(DIR, 'raw', stamp + '.xml.gz')
        with gzip.open(rp, 'wt', encoding='utf-8') as f: f.write(xml)
        log.info('message %s: %d chars -> %s', stamp, len(xml), rp)
        self.accept(e.delivery)                       # 保存できたので受領
        try:
            info = decode(xml, stamp)
        except Exception as ex:
            info = {'error': 'decode: %s' % ex}
            log.error(traceback.format_exc())
        info.update(at=t.isoformat(), raw=os.path.basename(rp), chars=len(xml))
        st = {}
        try: st = json.load(open(os.path.join(DIR, 'status.json')))
        except Exception: pass
        msgs = (st.get('messages') or [])[-49:] + [info]
        status(last=info, messages=msgs, count=(st.get('count') or 0) + 1)
        log.info('decoded: %s', json.dumps({k: v for k, v in info.items() if k != 'files'}, ensure_ascii=False))

    def _err(self, e, what):
        cond = (e.connection and (e.connection.remote_condition or e.connection.condition)) or \
               (e.transport and e.transport.condition) or (e.link and e.link.remote_condition)
        msg = '%s: %s' % (what, cond and ('%s %s' % (cond.name, cond.description)))
        log.error(msg)
        status(error=msg, errorAt=now().isoformat())
        e.container.stop()                            # systemd が待ってから起こし直す

    def on_transport_error(self, e): self._err(e, 'transport')
    def on_connection_error(self, e): self._err(e, 'connection')
    def on_link_error(self, e): self._err(e, 'link')
    def on_disconnected(self, e): self._err(e, 'disconnected')


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
    if not (USER and PASS and QUEUE):
        log.error('AIPD_USER / AIPD_PASS / AIPD_QUEUE が未設定(/etc/aipdist/env)'); sys.exit(2)
    for d in ('raw', 'zip', 'aixm'): os.makedirs(os.path.join(DIR, d), exist_ok=True)
    Container(Recv()).run()
    sys.exit(1)                                       # 止まったら異常終了扱い → systemd が再起動


if __name__ == '__main__':
    main()
