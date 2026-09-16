/* ADS-B 中継 (Vercel Functions / Node.js ランタイム / Hobby 無料プラン)
   ====================================================================
   adsb.lol と adsb.fi は Access-Control-Allow-Origin を返さないので、PWA から直接は読めない。
   ここで中継して、許可したオリジンにだけ CORS ヘッダを付けて返す。

   ⚠ なぜ Cloudflare Workers ではないのか:
     Workers から出る通信は Cloudflare の**共有の送信元IP**を使い、adsb.lol / adsb.fi はそこを
     403・429 で弾く(2026-09 に実機で 502 upstream を確認。同じ症状の公開事例あり)。
     **必ず Node.js ランタイムで動かすこと。Edge ランタイムにすると Cloudflare 網に乗って同じく弾かれる。**

   守り(Origin 照合・合言葉・IPごとの回数制限)は lib/guard.js。ここでは上流キャッシュだけ持つ。
     位置を GRID 度に丸めて UP_TTL 秒持つ。同じ空域の複数人が上流1回にまとまる(adsb.lol への気遣い)。
   Hobby の無料枠は月100万回・Active CPU 4時間。Hobby は**非商用の個人利用に限る**。
*/
import { check, preflight, json, num, makeLimiter } from '../lib/guard.js';

const UP_TTL_MS = 10_000;
const GRID = 0.05;                // 約5km
const overLimit = makeLimiter(12); // 15秒に1回なら毎分4回。3倍の余裕

const SRC = [
  { n: 'adsb.lol', u: (a, o, r) => `https://api.adsb.lol/v2/point/${a}/${o}/${r}`, k: 'ac' },
  { n: 'adsb.fi', u: (a, o, r) => `https://opendata.adsb.fi/api/v2/lat/${a}/lon/${o}/dist/${r}`, k: 'aircraft' },
];
const cache = new Map();          // key -> { t, body }

async function upstream(lat, lon, rad) {
  const why = [];
  for (const s of SRC) {
    try {
      const r = await fetch(s.u(lat, lon, rad), {
        headers: { 'User-Agent': 'heli-nav-pwa personal relay' },
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) { why.push(`${s.n} ${r.status}`); continue; }
      const o = await r.json();
      return { out: { src: s.n, ac: o[s.k] || [] } };
    } catch (e) { why.push(`${s.n} ${e.name || 'error'}`); }
  }
  return { why };
}

export const OPTIONS = preflight;

export async function GET(request) {
  const { H, url, deny } = check(request, overLimit);
  if (deny) return deny;

  const lat = num(url.searchParams.get('lat'), -90, 90);
  const lon = num(url.searchParams.get('lon'), -180, 180);
  const rad = Math.min(Math.max(parseInt(url.searchParams.get('r') || '50', 10) || 50, 1), 250);
  if (lat === null || lon === null) return json({ error: 'latlon' }, 400, H);

  const now = Date.now();
  for (const [k, v] of cache) if (now - v.t > UP_TTL_MS) cache.delete(k);
  const qa = (Math.round(lat / GRID) * GRID).toFixed(2);
  const qo = (Math.round(lon / GRID) * GRID).toFixed(2);
  const ck = `${qa}/${qo}/${rad}`;
  const c = cache.get(ck);
  if (c) return new Response(c.body, { status: 200, headers: H });

  const { out, why } = await upstream(qa, qo, rad);
  // ⚠ 上流の失敗理由(状態コード)は返す。弾かれ方がわからないと次の手が打てない
  if (!out) return json({ error: 'upstream', detail: why }, 502, H);
  const body = JSON.stringify(out);
  cache.set(ck, { t: now, body });
  return new Response(body, { status: 200, headers: H });
}
