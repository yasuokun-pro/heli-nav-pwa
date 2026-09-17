/* 中継の守り(他機情報 api/adsb.js と 気象 api/wx.js で共通)
   ⚠ 順番: Origin 照合 → 合言葉 → IPごとの回数制限。ここを通ったものだけが上流に行く。
   ⚠ 回数制限はインスタンス内メモリの近似(インスタンスが複数立つと別々に数える)。 */

export const ALLOW = [
  'https://yasuokun-pro.github.io',
  'http://localhost:8765',        // 手元で確認するとき用
];

export function corsHeaders(origin, ok) {
  return {
    'Access-Control-Allow-Origin': ok ? origin : 'null',
    'Vary': 'Origin',
    'Cache-Control': 'no-store',
    'Content-Type': 'application/json; charset=utf-8',
  };
}

export const json = (o, s, h) => new Response(JSON.stringify(o), { status: s, headers: h });

export function num(v, lo, hi) {
  const n = parseFloat(v);
  return Number.isFinite(n) && n >= lo && n <= hi ? n : null;
}

export function ipOf(request) {
  return (request.headers.get('x-forwarded-for') || '').split(',')[0].trim()
    || request.headers.get('x-real-ip') || '0';
}

export function makeLimiter(max, windowMs = 60_000) {
  const hits = new Map();
  return (ip, now = Date.now()) => {
    const slot = Math.floor(now / windowMs);
    for (const [k, v] of hits) if (v.slot !== slot) hits.delete(k);   // 古い窓は捨てる
    const h = hits.get(ip);
    if (!h) { hits.set(ip, { slot, n: 1 }); return false; }
    if (h.n >= max) return true;
    h.n++;
    return false;
  };
}

export function preflight(request) {
  const origin = request.headers.get('origin') || '';
  const ok = ALLOW.includes(origin);
  return new Response(null, {
    status: ok ? 204 : 403,
    headers: { ...corsHeaders(origin, ok), 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '86400' },
  });
}

/* 引数の読み出し。**POST の本文(JSON)を優先**する。
   ⚠ 位置と合言葉を URL に入れると、Vercel の実行ログなどにそのまま残る。本文なら残らない(v6-178)。
     アプリは Content-Type: text/plain で送る(CORS の事前確認が要らない単純リクエストになる)。
   ⚠ GET(URL の ? 以降)は古い版のアプリのために当面残している。全端末が更新されたら外す。 */
async function paramsOf(request) {
  if (request.method === 'POST') {
    const t = await request.text();
    if (t.length > 4000) return null;
    let o;
    try { o = JSON.parse(t || '{}'); } catch (e) { return null; }
    if (!o || typeof o !== 'object') return null;
    return { get: k => (o[k] == null ? null : String(o[k])) };
  }
  const u = new URL(request.url);
  return { get: k => u.searchParams.get(k) };
}

/* 通れば { H, p } を、止めるなら { H, deny } を返す。p.get('lat') のように読む */
export async function check(request, overLimit) {
  const origin = request.headers.get('origin') || '';
  const ok = ALLOW.includes(origin);
  const H = corsHeaders(origin, ok);
  if (!ok) return { H, deny: json({ error: 'origin' }, 403, H) };
  const p = await paramsOf(request);
  if (!p) return { H, deny: json({ error: 'body' }, 400, H) };
  const key = process.env.RELAY_KEY;
  // ⚠ RELAY_KEY 未設定のときは誰も通さない(設定し忘れて素通しになるのを防ぐ)
  if (!key || p.get('k') !== key) return { H, deny: json({ error: 'key' }, 403, H) };
  if (overLimit(ipOf(request))) return { H, deny: json({ error: 'rate' }, 429, H) };
  return { H, p };
}
