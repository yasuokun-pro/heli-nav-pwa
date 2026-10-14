#!/bin/bash
# SWIM AIP データ配信の受信を Oracle VM(DIPS 用と同じ VM)に入れる。
#   scp -i ~/.ssh/heli_nav_oci tools/aip-dist/{setup.sh,receiver.py} ubuntu@<固定IP>:
#   ssh -i ~/.ssh/heli_nav_oci ubuntu@<固定IP> sudo bash setup.sh <受信キューID> <キュー接続用認証ID>
# パスワードは**このあと本人が**入れる:  ssh -t ... sudo aipdist-pass   (画面に出ない入力)
set -euo pipefail
QUEUE="${1:?受信キューID}"; USER_ID="${2:?キュー接続用認証ID}"

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-qpid-proton ca-certificates >/dev/null

# 1GB の VM で数十MB〜の XML を扱うので swap を 2GB 足す(既にあれば何もしない)
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

id aipdist >/dev/null 2>&1 || useradd --system --home /var/lib/aipdist --shell /usr/sbin/nologin aipdist
install -d -o aipdist -g aipdist -m 750 /var/lib/aipdist
install -d -m 750 /etc/aipdist
install -m 755 receiver.py /usr/local/lib/aipdist-receiver.py

# 資格情報(root・600)。パスワードは空のまま作り、aipdist-pass で本人が入れる
if [ ! -f /etc/aipdist/env ]; then
  printf 'AIPD_URL=amqps://amq.swim.mlit.go.jp:5671\nAIPD_USER=%s\nAIPD_QUEUE=%s\nAIPD_PASS=\nAIPD_DIR=/var/lib/aipdist\n' "$USER_ID" "$QUEUE" > /etc/aipdist/env
else
  sed -i "s|^AIPD_USER=.*|AIPD_USER=$USER_ID|; s|^AIPD_QUEUE=.*|AIPD_QUEUE=$QUEUE|" /etc/aipdist/env
fi
chmod 600 /etc/aipdist/env

cat > /usr/local/sbin/aipdist-pass <<'EOF'
#!/bin/bash
# キュー接続用パスワードを入れる(画面に出さない)。入れたら受信を起こし直す
set -euo pipefail
read -r -s -p 'キュー接続用パスワード: ' P; echo
[ -n "$P" ] || { echo '空なので中止'; exit 1; }
tmp=$(mktemp); chmod 600 "$tmp"
grep -v '^AIPD_PASS=' /etc/aipdist/env > "$tmp"; printf 'AIPD_PASS=%s\n' "$P" >> "$tmp"
install -m 600 "$tmp" /etc/aipdist/env; rm -f "$tmp"; unset P
systemctl restart aipdist && sleep 8 && systemctl --no-pager -n 6 status aipdist | tail -6
EOF
chmod 700 /usr/local/sbin/aipdist-pass

cat > /etc/systemd/system/aipdist.service <<'EOF'
[Unit]
Description=SWIM AIP data distribution receiver (AMQP)
After=network-online.target
Wants=network-online.target
# 失敗が続いても SWIM を叩きすぎない(1時間に最大20回)。⚠ この2つは [Unit] に書く([Service] だと無視される)
StartLimitIntervalSec=3600
StartLimitBurst=20

[Service]
User=aipdist
EnvironmentFile=/etc/aipdist/env
ExecStart=/usr/bin/python3 /usr/local/lib/aipdist-receiver.py
Restart=always
RestartSec=60
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/aipdist
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable aipdist >/dev/null
# パスワードが入るまでは起動しない
if grep -q '^AIPD_PASS=.\+' /etc/aipdist/env; then systemctl restart aipdist; fi
echo "OK: 受信の準備ができました。次に  sudo aipdist-pass  でキュー接続用パスワードを入れてください"
