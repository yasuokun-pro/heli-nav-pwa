#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SWIM AIP データ配信の受信の見張り(Oracle VM・systemd timer で3時間ごと・root)
==========================================================================
2026-10-14〜11-09 に、受信プログラムが**接続したまま何も受け取らない**状態で止まっていた(TCP は ESTAB・ログも無言)。
再起動した瞬間に溜まっていた差分が届いたので、「つなぎ直せば来る」。そこで:
  1. つなぎ直し … 受信が24時間以上続いていたら再起動する(直前10分に受信があれば待つ)。
     受信プログラムは保存してから accept するので、受信の途中で切っても取りこぼさない(キューに残って次に届く)
  2. 届くはずの版の確認 … AIP は AIRAC ごと(28日)に、発効の約2週間前に配信される(11/26 版は 11/12)。
     次の発効日の **12日前を過ぎてもその版(publication = 発効日の前日 15:00Z)が来ていなければ**、再起動して通知する
  3. 受信プログラムが動いていない・エラーが続いている → 通知
  4. 新しい版を受け取った → 通知(何が届いたか分かる。**来るはずの時期に通知が無い = おかしい**とも気づける)
通知は ntfy.sh(無料・登録不要)。トピック名は /etc/aipdist/env の AIPD_NTFY(**リポジトリ・公開の場に書かない**)。
空なら journal に書くだけ。同じ種類の通知は1日1回まで。
状態: /var/lib/aipdist/watch.json(受け取った版の一覧・通知と再起動の時刻)

使い方: aipdist-watch [--test]   --test … 通知を1通送って届くか確かめる
"""
import os, re, sys, glob, json, time, datetime, subprocess, urllib.request

DIR = os.environ.get('AIPD_DIR', '/var/lib/aipdist')
TOPIC = os.environ.get('AIPD_NTFY', '')
ST = os.path.join(DIR, 'watch.json')
AIRAC0 = datetime.date(2026, 10, 29)          # AIRAC の発効日の基準(28日おき)
DUE = 12                                      # 発効の何日前までに届いていなければおかしいか
RE_PUB = re.compile(r'<gco:DateTime>([^<]+)</gco:DateTime>\s*</gmd:date>\s*<gmd:dateType>\s*<gmd:CI_DateTypeCode[^>]*codeListValue="publication"')


def now(): return datetime.datetime.now(datetime.timezone.utc)
def iso(t): return t.isoformat(timespec='seconds')
def log(*a): print(*a, flush=True)


def load():
    try: return json.load(open(ST))
    except Exception: return {}


def save(st):
    json.dump(st, open(ST + '.tmp', 'w'), ensure_ascii=False, indent=1); os.replace(ST + '.tmp', ST)


def notify(st, kind, title, msg, prio=4, tags=('warning',), force=False):
    """同じ kind は1日1回まで"""
    last = st.setdefault('sent', {}).get(kind)
    if last and not force and now() - datetime.datetime.fromisoformat(last) < datetime.timedelta(hours=23):
        log('通知は済み', kind); return
    log('通知', kind, title, msg)
    st['sent'][kind] = iso(now())
    if not TOPIC: return
    body = json.dumps({'topic': TOPIC, 'title': title, 'message': msg, 'priority': prio, 'tags': list(tags)}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request('https://ntfy.sh/', data=body, headers={'Content-Type': 'application/json'}), timeout=20)
    except Exception as ex:
        log('通知に失敗', ex); st['sent'].pop(kind, None)


def received(st):
    """aixm/<受信時刻>/ の AIXM_*.xml の先頭から版(publication)を読む。新しく見つけたものを返す"""
    seen = st.setdefault('seen', {})
    new = []
    for d in sorted(glob.glob(os.path.join(DIR, 'aixm', '*'))):
        k = os.path.basename(d)
        if k in seen: continue
        fs = sorted(glob.glob(os.path.join(d, 'AIXM_*.xml')))
        if not fs: continue
        head = open(fs[0], 'rb').read(16384).decode('utf-8', 'replace')
        m = RE_PUB.search(head)
        seen[k] = {'file': os.path.basename(fs[0]), 'pub': m.group(1) if m else None}
        new.append(seen[k])
    return new


def svc(prop):
    return subprocess.run(['systemctl', 'show', '-p', prop, '--value', 'aipdist'], capture_output=True, text=True).stdout.strip()


def restart(st, why):
    log('再起動:', why)
    subprocess.run(['systemctl', 'restart', 'aipdist'])
    st['restarted'] = iso(now()); st['restartWhy'] = why


def next_airac(today):
    n = -(-(today - AIRAC0).days // 28) if today > AIRAC0 else 0
    e = AIRAC0 + datetime.timedelta(days=28 * n)
    return e if e > today else e + datetime.timedelta(days=28)


def main():
    st = load()
    first = 'seen' not in st
    t = now()
    if '--test' in sys.argv:
        notify(st, 'test', 'HELI NAV 受信の見張り', '通知のテストです(%s UTC)' % t.strftime('%m/%d %H:%M'), prio=3, tags=('white_check_mark',), force=True)
        save(st); return

    # 4. 新しく届いた版(初回は今あるものを覚えるだけ)
    for r in received(st):
        if first: continue
        pub = (r['pub'] or '')[:10]
        eff = (datetime.date.fromisoformat(pub) + datetime.timedelta(days=1)).strftime('%Y-%m-%d') if pub else '不明'
        notify(st, 'got:' + r['file'], 'AIP データが届きました', '%s(発効 %s)。Mac に持ってきて aixm_apply_diff.py を回す' % (r['file'], eff),
               prio=3, tags=('inbox_tray',), force=True)

    # 3. 受信プログラムの状態
    active = svc('ActiveState')
    if active != 'active':
        notify(st, 'down', 'AIP 受信が止まっています', 'aipdist が %s。ssh して journalctl -u aipdist を見る' % active)
    try: s = json.load(open(os.path.join(DIR, 'status.json')))
    except Exception: s = {}
    if s.get('error') and s.get('errorAt') and (not s.get('connected') or s['connected'] < s['errorAt']):
        notify(st, 'error', 'AIP 受信でエラー', '%s(%s)' % (s['error'][:200], s['errorAt'][:16]))

    # 1. つなぎ直し(24時間ごと)
    up = None
    try:
        mono = int(svc('ActiveEnterTimestampMonotonic') or 0) / 1e6
        up = float(open('/proc/uptime').read().split()[0]) - mono if mono else None
    except Exception: pass
    last_at = (s.get('last') or {}).get('at')
    busy = last_at and t - datetime.datetime.fromisoformat(last_at) < datetime.timedelta(minutes=10)
    if active == 'active' and up and up > 24 * 3600 and not busy:
        restart(st, '定期のつなぎ直し(%.0f時間)' % (up / 3600))

    # 2. 届くはずの版が来ているか
    e = next_airac(t.date())
    want = (e - datetime.timedelta(days=1)).isoformat()
    have = sorted({(v.get('pub') or '')[:10] for v in st['seen'].values() if v.get('pub')})
    st['next'] = {'eff': e.isoformat(), 'due': (e - datetime.timedelta(days=DUE)).isoformat(), 'got': want in have}
    if t.date() >= e - datetime.timedelta(days=DUE) and want not in have:
        rs = st.get('restarted')
        if not rs or t - datetime.datetime.fromisoformat(rs) > datetime.timedelta(hours=6):
            restart(st, '%s 版が未着' % e)
        notify(st, 'missing:' + e.isoformat(), 'AIP %s 版が届いていません' % e.strftime('%m/%d'),
               '発効の%d日前を過ぎても来ていない(受信済み: %s)。自動で再起動した。SWIM のお知らせと ssh で journalctl -u aipdist を確認' % (DUE, ', '.join(have[-3:]) or 'なし'))
    st['checked'] = iso(t)
    save(st)
    log('確認', iso(t), '稼働', active, '連続 %.1fh' % (up / 3600) if up else '', '次の発効', e, '到着' if want in have else '未着')


if __name__ == '__main__':
    main()
