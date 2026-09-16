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
    headers: { ...corsHeaders(origin, ok), 'Access-Control-Allow-Methods': 'GET,OPTIONS', 'Access-Control-Max-Age': '86400' },
  });
}

/* 通れば { H, url } を、止めるなら { H, deny } を返す */
export function check(request, overLimit) {
  const origin = request.headers.get('origin') || '';
  const ok = ALLOW.includes(origin);
  const H = corsHeaders(origin, ok);
  if (!ok) return { H, deny: json({ error: 'origin' }, 403, H) };
  const url = new URL(request.url);
  const key = process.env.RELAY_KEY;
  // ⚠ RELAY_KEY 未設定のときは誰も通さない(設定し忘れて素通しになるのを防ぐ)
  if (!key || url.searchParams.get('k') !== key) return { H, deny: json({ error: 'key' }, 403, H) };
  if (overLimit(ipOf(request))) return { H, deny: json({ error: 'rate' }, 429, H) };
  return { H, url };
}
