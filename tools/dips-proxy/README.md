# DIPS 用の固定IPプロキシ (Oracle Cloud)

DIPS2.0 の API は**接続元の固定IPしか受け付けない**(2026-09-28 無人航空機安全課の回答)。
申請時には次の3点すべてに「はい」と答える必要がある:

1. 利用期間中に、クラウド事業者によって第三者へ再割り当てされない
2. 停止・再起動・再作成・障害復旧があっても同じIPが維持される
3. 自分に専有的に割り当てられている

Vercel の送信元IPは固定されないので、**Oracle Cloud の予約済みパブリックIP**を持つ小さな VM を置き、
中継(`relay/api/dips.js`)から DIPS への通信だけをそこ経由で出す。
予約済みIPは VM と独立してアカウントに残り、VM を作り直しても付け直せるので 1〜3 を満たす。

```
アプリ ──POST──▶ Vercel (relay/api/dips.js・client_secret はここだけ)
                    │ CONNECT (TLS・Basic認証)
                    ▼
                 Oracle VM (squid・固定IP)  ── DIPS の4ホストの443番だけ通す
                    │ TLS はそのまま通し(VM からは中身が見えない)
                    ▼
                 DIPS (www.dips-reg / www.uafpi / 検証環境の2つ)
```

## 手順

### 1. アカウント(利用者本人が行う)
- <https://signup.cloud.oracle.com/> で作成。クレジットカードの登録が要る(本人確認用)
- **ホーム・リージョンは Japan East (Tokyo)**。⚠ あとから変えられない。無料枠はホーム・リージョンでしか効かない
- 作成後、**請求 → アップグレード で Pay As You Go(従量課金)に切り替える**
  - ⚠ Always Free のままだと **7日間ほぼアイドルの VM は回収される**。中継だけの VM は必ずアイドル判定になる
  - 無料枠の範囲なら請求は0円。**予算アラート**(請求とコスト管理 → 予算)を金額1円・実績100%で作っておく

### 2. VM(コンソールで作る)
- コンピュート → インスタンス → 作成
  - イメージ: **Canonical Ubuntu 24.04**
  - シェイプ: **VM.Standard.E2.1.Micro**(「Always Free 対象」の印があるもの)
  - ネットワーク: 新しい VCN・パブリック・サブネット
  - SSH キー: **公開キーを貼る**(`~/.ssh/heli_nav_oci.pub`。秘密鍵は利用者の Mac にだけある)
- 作成後、**IP を予約済みに替える**: インスタンス → アタッチされた VNIC → IPv4 アドレス → ︙ → 編集
  → 「パブリック IP なし」で保存 → もう一度編集 → **予約済みパブリック IP → 新規作成**
- **受信ルール**: VCN → セキュリティ・リスト → Default → イングレス・ルールの追加
  ソース `0.0.0.0/0`・TCP・宛先ポート **3129**
  (Vercel の送信元IPは固定されないので絞れない。代わりに TLS+長い合言葉+宛先の限定で守る)

### 3. プロキシの設定(SSH で)
```bash
scp -i ~/.ssh/heli_nav_oci tools/dips-proxy/setup.sh ubuntu@<固定IP>:
ssh -i ~/.ssh/heli_nav_oci ubuntu@<固定IP> sudo bash setup.sh
```
squid・OS の自動更新(JST 04:00 に必要なら再起動)・iptables・SSH の鍵限定までやる。
終わると VM の `/root/dips-proxy/vercel-env.txt` に Vercel へ入れる値ができる。

### 4. Vercel の環境変数(利用者本人が入れる)
| 変数 | 値 | いつ |
|---|---|---|
| `DIPS_PROXY` | `https://relay:<合言葉>@<固定IP>:3129` | VM ができたら |
| `DIPS_PROXY_CA` | VM の `ca.pem` の中身(`-----BEGIN CERTIFICATE-----` から全部) | 同上 |
| `DIPS_ENV` | `stg`(検証)→ 本番承認後に `prod` | 通知が来たら |
| `DIPS_CLIENT_ID` / `DIPS_CLIENT_SECRET` | 航空局から通知される値 | 同上 |
| `DIPS_REDIRECT` | `https://yasuokun-pro.github.io/heli-nav-pwa/`(申請書 3-1 と完全一致) | 同上 |

⚠ **これらの値はリポジトリにもチャットにも書かない。**

### 5. DIPS へ申請
申請書(`aip/docs/申請書_記入済み/DIPS2.0_API利用申請書_船水.xlsx`・リポジトリ外)の 3-2 に固定IPを書き、
確認事項 (1)〜(3) すべて「はい」をメール本文に添えて hqt-jcab.mujin@ki.mlit.go.jp へ。

## 運用
- 月1回くらい、中継の接続テストで DIPS まで届くかを見る(届かなければ VM が止まっている)
- ⚠ **IP を手放す前**(VM の削除で「予約済みIPも削除」を選ぶ・アカウント解約)に、DIPS へ**停止申請**を出すこと。
  放すとその IP が他人に渡り、DIPS への接続を許してしまう(申請条件 1 の理由)
- 合言葉を替えるとき: VM で `sudo rm /etc/squid/passwd && sudo bash setup.sh` → Vercel の `DIPS_PROXY` を差し替え
