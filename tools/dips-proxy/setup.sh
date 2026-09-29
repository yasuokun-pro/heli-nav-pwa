#!/bin/bash
# DIPS 用の固定IPプロキシ(Oracle Cloud の Ubuntu VM で1回だけ実行する)
# ============================================================
# 役割: Vercel の中継(relay/api/dips.js)から来る CONNECT を、DIPS の4ホストの443番にだけ通す。
#   ・TLS はDIPSまで通しなので、client_secret・トークン・飛行計画はこの VM からは見えない
#   ・プロキシとの間も TLS(自己署名・名前 dips-proxy)+ Basic 認証。合言葉は長い乱数
#   ・DIPS 以外の宛先は 403。平文の http_port は localhost だけ
# 実行: sudo bash setup.sh
# 終わると /root/dips-proxy/ に **Vercel に入れる値**(DIPS_PROXY・DIPS_PROXY_CA)が出る。
# ⚠ その値はリポジトリ・チャットに貼らないこと。Vercel の環境変数にだけ入れる。
set -euo pipefail
PORT=3129
OUT=/root/dips-proxy
mkdir -p "$OUT" && chmod 700 "$OUT"

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q squid-openssl apache2-utils unattended-upgrades openssl

# ── OSの自動更新(セキュリティ更新を毎日・必要なら 04:00 JST に再起動) ──
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'X'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
X
sed -i 's|^//\?\s*Unattended-Upgrade::Automatic-Reboot .*|Unattended-Upgrade::Automatic-Reboot "true";|' /etc/apt/apt.conf.d/50unattended-upgrades
grep -q 'Automatic-Reboot "true"' /etc/apt/apt.conf.d/50unattended-upgrades || echo 'Unattended-Upgrade::Automatic-Reboot "true";' >> /etc/apt/apt.conf.d/50unattended-upgrades
grep -q 'Automatic-Reboot-Time' /etc/apt/apt.conf.d/50unattended-upgrades || echo 'Unattended-Upgrade::Automatic-Reboot-Time "19:00";' >> /etc/apt/apt.conf.d/50unattended-upgrades   # UTC 19:00 = JST 04:00

# ── 証明書(自己署名・名前 dips-proxy・10年) ──
if [ ! -f /etc/squid/dips-proxy.pem ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
    -keyout /etc/squid/dips-proxy.key -out /etc/squid/dips-proxy.pem -days 3650 \
    -subj "/CN=dips-proxy" -addext "subjectAltName=DNS:dips-proxy"
  chown proxy:proxy /etc/squid/dips-proxy.key && chmod 600 /etc/squid/dips-proxy.key
fi

# ── 合言葉(Basic 認証) ──
if [ ! -f /etc/squid/passwd ]; then
  PW=$(openssl rand -base64 36 | tr -d '/+=' | cut -c1-40)
  htpasswd -bcm /etc/squid/passwd relay "$PW" >/dev/null
  chown proxy:proxy /etc/squid/passwd && chmod 600 /etc/squid/passwd
  echo "$PW" > "$OUT/password" && chmod 600 "$OUT/password"
fi

cat > /etc/squid/squid.conf <<X
# DIPS 専用の転送プロキシ(tools/dips-proxy/setup.sh が生成。手で直したらそちらにも反映)
https_port $PORT tls-cert=/etc/squid/dips-proxy.pem tls-key=/etc/squid/dips-proxy.key
http_port 127.0.0.1:3128

auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic realm dips
auth_param basic credentialsttl 1 hour
acl authed proxy_auth REQUIRED

acl dips dstdomain www.dips-reg.mlit.go.jp www.uafpi.dips.mlit.go.jp www.stg.uafp.dips.mlit.go.jp www.stg.uafpi.dips.mlit.go.jp
acl SSL_ports port 443
acl CONNECT method CONNECT

http_access deny !authed
http_access allow CONNECT dips SSL_ports
http_access deny all

cache deny all
via off
forwarded_for delete
# 宛先ホストと結果だけ残す(中身は TLS なので見えない)。30日で捨てる
logformat short %ts %>a %rm %ru %>Hs
access_log daemon:/var/log/squid/access.log short
logfile_rotate 30
X

# ── ファイアウォール(OCI の Ubuntu は iptables で 22 以外を閉じている) ──
if ! iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null; then
  iptables -I INPUT 5 -p tcp --dport $PORT -j ACCEPT
  apt-get install -y -q iptables-persistent
  netfilter-persistent save
fi

# ── SSH は鍵だけ ──
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd || true

squid -k parse
systemctl enable squid
systemctl restart squid

IP=$(curl -s https://ifconfig.me || echo '<固定IP>')
cp /etc/squid/dips-proxy.pem "$OUT/ca.pem"
cat > "$OUT/vercel-env.txt" <<X
DIPS_PROXY=https://relay:$(cat "$OUT/password")@$IP:$PORT
DIPS_PROXY_CA=
$(cat "$OUT/ca.pem")
X
chmod 600 "$OUT/vercel-env.txt"
echo
echo "完了。Vercel の環境変数に入れる値は $OUT/vercel-env.txt にあります(sudo cat で表示)。"
echo "送信元IP(DIPSの申請書に書くもの): $IP"
