/* ADS-B 中継 (Cloudflare Workers / 無料プラン)
   =========================================
   adsb.lol と adsb.fi は **Access-Control-Allow-Origin を返さない**ので、
   GitHub Pages に置いた PWA からは直接読めない(通信は届くがブラウザが結果を渡さない)。
   ここで中継して、**許可したオリジンにだけ** CORS ヘッダを付けて返す。

   ⚠ 中継URLは認証の無い公開エンドポイントになる。野ざらしにすると無料枠(1日10万回)を
     他人に食い潰される。対策を4枚重ねてある。どれも外さないこと。
       1. Origin 照合   … 許可した配信元から来たブラウザ以外は弾く
       2. 合言葉(k=)    … RELAY_KEY を Secret で持たせる。端末側は localStorage に置き、
                          **公開リポジトリには絶対に書かない**
       3. IPごとの上限  … 1分あたり MAX_PER_IP 回。超えたら 429
       4. 上流キャッシュ… 位置を粗く丸めて UP_TTL 秒だけ持つ。同じ空域の複数人が上流1回にまとまる
     ⚠ 4 が減らすのは **adsb.lol 側の負荷**。Cloudflare のリクエスト数は Worker が動く以上そのまま数える。

   ⚠ 無料枠を超えても課金にはならない。Error 1027 を返して止まり、**00:00 UTC(日本時間の朝9時)**に戻る。
*/

const ALLOW = [                 // ここに書いた配信元からのブラウザ要求だけ通す
  'https://yasuokun-pro.github.io',
  'http://localhost:8765',      // 手元で確認するとき用
];
const WINDOW = 60;              // IP制限の窓(秒)
const MAX_PER_IP = 12;          // 窓あたりの上限。15秒に1回なら毎分4回なので3倍の余裕
const UP_TTL = 10;              // 上流レスポンスを持つ秒数
const GRID = 0.05;              // 位置を丸める粒度(度)。約5km

const SRC = [
  { n: 'adsb.lol', u: (a, o, r) => `https://api.adsb.lol/v2/point/${a}/${o}/${r}`, k: 'ac' },
  { n: 'adsb.fi', u: (a, o, r) => `https://opendata.adsb.fi/api/v2/lat/${a}/lon/${o}/dist/${r}`, k: 'aircraft' },
];

const json = (o, s, h) => new Response(JSON.stringify(o), { status: s, headers: h });

function num(v, lo, hi) {
  const n = parseFloat(v);
  return Number.isFinite(n) && n >= lo && n <= hi ? n : null;
}

/* IPごとの回数制限。Cache API を1分ごとのバケツとして使う近似(コロ単位・厳密な原子性は無い)。
   個人用の中継を守るには十分で、Durable Objects を使わない分だけ無料プランで完結する */
async function overLimit(ip, ctx) {
  const slot = Math.floor(Date.now() / 1000 / WINDOW);
  const key = new Request(`https://relay.invalid/ip/${encodeURIComponent(ip)}/${slot}`);
  const cache = caches.default;
  const hit = await cache.match(key);
  const n = hit ? (parseInt(await hit.text(), 10) || 0) : 0;
  if (n >= MAX_PER_IP) return true;
  ctx.waitUntil(cache.put(key, new Response(String(n + 1), {
    headers: { 'Cache-Control': `max-age=${WINDOW}` },
  })));
  return false;
}

async function upstream(lat, lon, rad) {
  for (const s of SRC) {
    try {
      const r = await fetch(s.u(lat, lon, rad), {
        headers: { 'User-Agent': 'heli-nav-pwa personal relay' },
        cf: { cacheTtl: UP_TTL, cacheEverything: true },
      });
      if (!r.ok) continue;
      const o = await r.json();
      return { src: s.n, ac: o[s.k] || [] };
    } catch (e) { /* 次の上流へ */ }
  }
  return null;
}

export default {
  async fetch(req, env, ctx) {
    const origin = req.headers.get('Origin') || '';
    const ok = ALLOW.includes(origin);
    const H = {
      'Access-Control-Allow-Origin': ok ? origin : 'null',
      'Vary': 'Origin',
      'Cache-Control': 'no-store',
      'Content-Type': 'application/json; charset=utf-8',
    };

    if (req.method === 'OPTIONS') {
      return new Response(null, {
        status: ok ? 204 : 403,
        headers: { ...H, 'Access-Control-Allow-Methods': 'GET,OPTIONS', 'Access-Control-Max-Age': '86400' },
      });
    }
    if (req.method !== 'GET') return json({ error: 'method' }, 405, H);
    if (!ok) return json({ error: 'origin' }, 403, H);

    const u = new URL(req.url);
    // ⚠ RELAY_KEY を設定していない間は誰でも叩ける。必ず wrangler secret / ダッシュボードで入れること
    if (!env.RELAY_KEY || u.searchParams.get('k') !== env.RELAY_KEY)
      return json({ error: 'key' }, 403, H);

    const lat = num(u.searchParams.get('lat'), -90, 90);
    const lon = num(u.searchParams.get('lon'), -180, 180);
    const rad = Math.min(Math.max(parseInt(u.searchParams.get('r') || '50', 10) || 50, 1), 250);
    if (lat === null || lon === null) return json({ error: 'latlon' }, 400, H);

    const ip = req.headers.get('CF-Connecting-IP') || '0';
    if (await overLimit(ip, ctx)) return json({ error: 'rate' }, 429, H);

    const qa = (Math.round(lat / GRID) * GRID).toFixed(2);
    const qo = (Math.round(lon / GRID) * GRID).toFixed(2);
    const ck = new Request(`https://relay.invalid/a/${qa}/${qo}/${rad}`);
    const cache = caches.default;
    let hit = await cache.match(ck);
    if (!hit) {
      const out = await upstream(qa, qo, rad);
      if (!out) return json({ error: 'upstream' }, 502, H);
      hit = new Response(JSON.stringify(out), {
        headers: { 'Content-Type': 'application/json', 'Cache-Control': `max-age=${UP_TTL}` },
      });
      ctx.waitUntil(cache.put(ck, hit.clone()));
    }
    return new Response(await hit.text(), { status: 200, headers: H });
  },
};
