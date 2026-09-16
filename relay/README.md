# 他機情報の中継 (Vercel)

## なぜ Cloudflare Workers ではなくこちらか
`worker/adsb-relay.js` を Cloudflare Workers に置いたところ、Origin・合言葉・回数制限は
正しく働いたが、上流の取得で **`502 upstream`** になった(2026-09-16)。
Workers から出る通信は Cloudflare の**共有の送信元IP**を使い、adsb.lol と adsb.fi は
そこを 403・429 で断っている。同じ症状と、Vercel の Node.js ランタイムへ移して解決した
公開事例がある。手元のMacからは両方とも 200 で取れる。

⚠ **Node.js ランタイムで動かすこと。** Edge ランタイムにすると Cloudflare 網に乗って同じく弾かれる。

## 置き方 (ブラウザだけで完結)
1. <https://vercel.com/signup> で **Hobby**(無料)を GitHub アカウントで作る。支払い方法は不要。
2. **Add New → Project** で `yasuokun-pro/heli-nav-pwa` を Import。
3. 設定画面で
   - **Root Directory** を `relay` にする(ここが肝心。サイト全体を載せない)
   - Framework Preset は **Other**。Build Command などは空のまま
   - **Environment Variables** に `RELAY_KEY` = Cloudflare に入れたのと同じ文字列
4. **Deploy**。`https://<プロジェクト名>.vercel.app` が中継URL。
5. アプリの「他機」タブの中継設定で URL を差し替え、合言葉はそのままで 保存 → 接続テスト。

## 守りの4枚 (Worker 版と同じ順番・同じ返事)
| | 失敗時の返事 |
|---|---|
| Origin 照合 | 403 `origin` |
| 合言葉 `k=` (`RELAY_KEY` 未設定なら誰も通さない) | 403 `key` |
| IPごと1分12回 | 429 `rate` |
| 上流を0.05度に丸めて10秒キャッシュ | (上流失敗時は 502 `upstream` と `detail` に理由) |

⚠ 回数制限とキャッシュは**インスタンス内のメモリ**で持つ近似。インスタンスが複数立つと別々に数える。

## 無料枠 (Hobby)
月 **100万回**の関数呼び出し、Active CPU **4時間**、デプロイは1日100回まで。
15秒に1回なら1時間240回。リポジトリへの自動コミット(METAR)は1日20回前後で、
そのたびに再デプロイされるが上限には収まる。
⚠ Hobby は**非商用の個人利用に限る**(Vercel の規約)。

## 手元で試す
```bash
node /tmp/relay_test.mjs   # 試験スクリプトは会話中に作ったもの。api/adsb.js の GET/OPTIONS を直接呼ぶ
```
