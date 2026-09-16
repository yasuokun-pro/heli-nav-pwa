# 中継 (Vercel)

2つの窓口がある。どちらも同じ4つの鍵(`lib/guard.js`)を通る。

| 窓口 | 中身 | 上流 | 使い回し |
|---|---|---|---|
| `/api/adsb` (`/` も同じ) | 他機情報 | adsb.lol → adsb.fi | 位置を0.05度に丸めて10秒 |
| `/api/wx?ids=RJTT,...` | METAR 3時間ぶん + TAF | aviationweather.gov (NOAA) | 同じ局の組み合わせを2分 |

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
