/* ADS-B 中継 (Vercel Functions / Node.js ランタイム / Hobby 無料プラン)
   ====================================================================
   adsb.lol と adsb.fi は Access-Control-Allow-Origin を返さないので、PWA から直接は読めない。
   ここで中継して、許可したオリジンにだけ CORS ヘッダを付けて返す。

   ⚠ なぜ Cloudflare Workers ではないのか:
     Workers から出る通信は Cloudflare の**共有の送信元IP**を使い、adsb.lol / adsb.fi はそこを
     403・429 で弾く(2026-09 に実機で 502 upstream を確認。同じ症状の公開事例あり)。
     **必ず Node.js ランタイムで動かすこと。Edge ランタイムにすると Cloudflare 網に乗って同じく弾かれる。**

   守りは worker/adsb-relay.js と同じ4枚。順番も返事も揃えてある(アプリ側の表示が同じになる)。
     1. Origin 照合   … 許可した配信元から来たブラウザ以外は 403 origin
     2. 合言葉(k=)    … 環境変数 RELAY_KEY と一致しなければ 403 key。未設定なら誰も通さない
     3. IPごとの上限  … 1分あたり MAX_PER_IP 回を超えたら 429 rate
     4. 上流キャッシュ… 位置を GRID 度に丸めて UP_TTL 秒持つ。同じ空域の複数人が上流1回にまとまる
   ⚠ 3 と 4 は**インスタンス内のメモリ**で持つ近似。インスタンスが複数立つと別々に数える。
     個人用の中継を守るには十分で、外部ストアを使わない分だけ無料枠で完結する。

   Hobby の無料枠は月100万回・Active CPU 4時間。15秒に1回なら1時間240回。
   Hobby は**非商用の個人利用に限る**(Vercel の規約)。
*/

const ALLOW = [
  'https://yasuokun-pro.github.io',
  'http://localhost:8765',        // 手元で確認するとき用
];
const WINDOW_MS = 60_000;
const MAX_PER_IP = 12;            // 15秒に1回なら毎分4回。3倍の余裕
const UP_TTL_MS = 10_000;
const GRID = 0.05;                // 約5km

const SRC = [
  { n: 'adsb.lol', u: (a, o, r) => `https://api.adsb.lol/v2/point/${a}/${o}/${r}`, k: 'ac' },
  { n: 'adsb.fi', u: (a, o, r) => `https://opendata.adsb.fi/api/v2/lat/${a}/lon/${o}/dist/${r}`, k: 'aircraft' },
];

const hits = new Map();           // ip -> { slot, n }
const cache = new Map();          // key -> { t, body }

function headers(origin, ok) {
  return {
    'Access-Control-Allow-Origin': ok ? origin : 'null',
    'Vary': 'Origin',
    'Cache-Control': 'no-store',
    'Content-Type': 'application/json; charset=utf-8',
  };
}
const json = (o, s, h) => new Response(JSON.stringify(o), { status: s, headers: h });

function num(v, lo, hi) {
  const n = parseFloat(v);
  return Number.isFinite(n) && n >= lo && n <= hi ? n : null;
}

function overLimit(ip, now = Date.now()) {
  const slot = Math.floor(now / WINDOW_MS);
  const h = hits.get(ip);
  if (!h || h.slot !== slot) { hits.set(ip, { slot, n: 1 }); return false; }
  if (h.n >= MAX_PER_IP) return true;
  h.n++;
  return false;
}

function sweep(now = Date.now()) {  // メモリが膨らまないように古いものを捨てる
  const slot = Math.floor(now / WINDOW_MS);
  for (const [k, v] of hits) if (v.slot !== slot) hits.delete(k);
  for (const [k, v] of cache) if (now - v.t > UP_TTL_MS) cache.delete(k);
}

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

export function OPTIONS(request) {
  const origin = request.headers.get('origin') || '';
  const ok = ALLOW.includes(origin);
  return new Response(null, {
    status: ok ? 204 : 403,
    headers: { ...headers(origin, ok), 'Access-Control-Allow-Methods': 'GET,OPTIONS', 'Access-Control-Max-Age': '86400' },
  });
}

export async function GET(request) {
  const origin = request.headers.get('origin') || '';
  const ok = ALLOW.includes(origin);
  const H = headers(origin, ok);
  if (!ok) return json({ error: 'origin' }, 403, H);

  const u = new URL(request.url);
  const key = process.env.RELAY_KEY;
  // ⚠ RELAY_KEY 未設定のときは誰も通さない(設定し忘れて素通しになるのを防ぐ)
  if (!key || u.searchParams.get('k') !== key) return json({ error: 'key' }, 403, H);

  const lat = num(u.searchParams.get('lat'), -90, 90);
  const lon = num(u.searchParams.get('lon'), -180, 180);
  const rad = Math.min(Math.max(parseInt(u.searchParams.get('r') || '50', 10) || 50, 1), 250);
  if (lat === null || lon === null) return json({ error: 'latlon' }, 400, H);

  const now = Date.now();
  sweep(now);
  const ip = (request.headers.get('x-forwarded-for') || '').split(',')[0].trim()
    || request.headers.get('x-real-ip') || '0';
  if (overLimit(ip, now)) return json({ error: 'rate' }, 429, H);

  const qa = (Math.round(lat / GRID) * GRID).toFixed(2);
  const qo = (Math.round(lon / GRID) * GRID).toFixed(2);
  const ck = `${qa}/${qo}/${rad}`;
  const c = cache.get(ck);
  if (c && now - c.t <= UP_TTL_MS) return new Response(c.body, { status: 200, headers: H });

  const { out, why } = await upstream(qa, qo, rad);
  // ⚠ 上流の失敗理由(状態コード)は返す。弾かれ方がわからないと次の手が打てない
  if (!out) return json({ error: 'upstream', detail: why }, 502, H);
  const body = JSON.stringify(out);
  cache.set(ck, { t: now, body });
  return new Response(body, { status: 200, headers: H });
}
