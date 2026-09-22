# 中継 (Vercel)

3つの窓口がある。どれも同じ4つの鍵(`lib/guard.js`)を通る。

| 窓口 | 中身 | 上流 | 使い回し |
|---|---|---|---|
| `/api/adsb` (`/` も同じ) | 他機情報 | adsb.lol → adsb.fi | 位置を0.05度に丸めて10秒 |
| `/api/wx?ids=RJTT,...` | METAR 3時間ぶん + TAF | aviationweather.gov (NOAA) | 同じ局の組み合わせを2分 |
| `/api/notam` 本文 `{"ids":"RJTT,..."}` | NOTAM(最大8飛行場) | FAA NOTAM API | 同じ組み合わせを10分 |

## NOTAM を使うのに要るもの
取得元は環境変数で切り替わる。**どちらも未設定なら 503 `{"error":"key"}`** を返し、アプリはその旨を画面に出す。

| 取得元 | 環境変数 | 状況(2026-09) |
|---|---|---|
| autorouter.aero (既定) | `AR_USER` / `AR_PASS` | **API利用合意が要る**。合意が取れるまで設定しないこと |
| FAA NOTAM API | `FAA_CLIENT_ID` / `FAA_CLIENT_SECRET` | ポータルが login.gov の**身元確認(米国発行の身分証)**を要求。日本からは事実上取れない |

⚠ autorouter の規約: "Use of autorouter's API ... is prohibited unless an API usage agreement is in place"。
  先に許可を取ること。`client_id` はアカウントのメール、`client_secret` は**アカウントのパスワードそのもの**なので、
  **他で使っていないパスワード**にすること。トークンは1時間で切れる(中継が自動で取り直す・同時20個まで)。
⚠ FAA 側は1回の要求で飛行場1つなので ids の数だけ並列に投げる(上限8)。autorouter は1回でまとめて引ける。
  どちらも上流を叩くので、IPごとの回数制限はこの窓口だけ **1分6回**。
⚠ **公式ブリーフィングの代わりにはならない**。国内の正式な情報源は AIS Japan と部隊のブリーフィング。
  自衛隊飛行場や国内限定の通知は ICAO 配信に流れてこないことがあるので、
  **出ない=異常なし ではない**。アプリ側にも同じ注意書きを出している。

## 送り方(v6-178〜)
アプリは **POST の本文**に `{"lat","lon","r","k"}` や `{"ids","k"}` を JSON で入れて送る。
位置と合言葉を URL に入れると Vercel の実行ログなどに残るため。位置はアプリ側で約5km に丸めてから送る。
GET(`?lat=...&k=...`)は古い版のアプリのために当面受けているが、全端末が更新されたら外す。

## 気象を中継で取る理由
NOAA も CORS の許可票を返さないので、これまでは GitHub Actions が30分おきに `metar.json` を作っていた。
**ところが定期実行は GitHub の混雑で飛ばされ、実際は3〜6時間に1回しか動いていなかった**(2026-09 の実行記録)。
中継ならアプリが開かれた時点で最新を取れる。`metar.json` は中継が無い・失敗したときの控えとして残してある。

⚠ NOAA の利用条件は「1分100回まで・1回400件まで・User-Agent を付ける」。超えるとアクセスを止められる。
アプリは40局ずつに分けて投げ、中継側は同じ組み合わせを2分使い回す。
⚠ 自衛隊飛行場(立川・館山・下総・木更津・入間・厚木・宇都宮・小牧・浜松)は **NOAA に流れていない**。
中継を通しても増えない。IMOC 等から取ってくるのは許可の無い再配信になるので**やらない**。

---

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
