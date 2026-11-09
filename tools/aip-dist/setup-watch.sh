#!/bin/bash
# AIP 受信の見張り(watch.py)を VM に入れる。setup.sh の後(受信が動いている VM)で:
#   scp -i ~/.ssh/heli_nav_oci tools/aip-dist/{setup-watch.sh,watch.py} ubuntu@<固定IP>:
#   ssh -i ~/.ssh/heli_nav_oci ubuntu@<固定IP> sudo bash setup-watch.sh
# 通知先の ntfy トピック名は初回にランダムで作って /etc/aipdist/env の AIPD_NTFY に入れる(既にあれば変えない)。
# スマホの ntfy アプリでそのトピックを購読する。トピック名を知っていれば誰でも読めるので公開の場に書かない
set -euo pipefail
install -m 755 watch.py /usr/local/lib/aipdist-watch.py
grep -q '^AIPD_NTFY=' /etc/aipdist/env || printf 'AIPD_NTFY=hnav-aipd-%s\n' "$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> /etc/aipdist/env
chmod 600 /etc/aipdist/env

cat > /usr/local/sbin/aipdist-watch <<'EOF'
#!/bin/bash
set -a; . /etc/aipdist/env; set +a
exec /usr/bin/python3 /usr/local/lib/aipdist-watch.py "$@"
EOF
chmod 700 /usr/local/sbin/aipdist-watch

cat > /etc/systemd/system/aipdist-watch.service <<'EOF'
[Unit]
Description=SWIM AIP data distribution receiver watchdog

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/aipdist-watch
EOF
cat > /etc/systemd/system/aipdist-watch.timer <<'EOF'
[Unit]
Description=Check the SWIM AIP receiver every 3 hours

[Timer]
OnBootSec=15min
OnUnitActiveSec=3h
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now aipdist-watch.timer >/dev/null
/usr/local/sbin/aipdist-watch
echo "OK: 見張りを入れました(3時間ごと)。通知のトピック: sudo grep AIPD_NTFY /etc/aipdist/env"
