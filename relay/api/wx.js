/* 気象(METAR・TAF)中継 (Vercel Functions / Node.js ランタイム)
   ==========================================================
   aviationweather.gov(米国 NOAA)も Access-Control-Allow-Origin を返さないので PWA から直接は読めない。
   これまでは GitHub Actions が30分おきに metar.json を作っていたが、**定期実行は混雑で飛ばされ、
   実際には3〜6時間に1回しか動いていなかった**(2026-09 の実行記録)。ここでその場で取る。

   GET /api/wx?ids=RJTT,RJAA,...&k=合言葉
     → { updated, src:'relay', m:{ICAO:{raw,cat,temp,wdir,wspd,visib,obs,hist[]}}, t:{ICAO:{raw,issue,from,to}}, tafErr? }
     m の形は metar.json と同じ(アプリは同じ描画を使う)。t は TAF。

   ⚠ NOAA の利用条件: 1分100回まで・1回400件まで・User-Agent を付けること。超えるとアクセスを止められる。
     → ids は1回80局まで(アプリは40局ずつに分けて投げる)。同じ ids は UP_TTL 秒使い回す。
     METAR は毎時更新なので2分の使い回しで「最新」の実用上の差は無い。
   ⚠ 自衛隊飛行場(立川・館山・下総など)は NOAA に**流れていない**。ここを通しても増えない。
     IMOC 等から取ってくるのは許可の無い再配信なので**やらない**(アプリはリンクで誘導するだけ)。
   ⚠ METAR が取れなければ 502(アプリは metar.json に戻る)。TAF だけ失敗したときは METAR を返して tafErr を付ける。
*/
import { check, preflight, json, makeLimiter } from '../lib/guard.js';

const UP_TTL_MS = 120_000;
const MAX_IDS = 80;
const overLimit = makeLimiter(12);
const cache = new Map();          // ids -> { t, body }
const UA = { 'User-Agent': 'heli-nav-pwa personal relay' };

async function getJson(u) {
  let last = 'error';
  for (let i = 0; i < 2; i++) {     // NOAA はたまに 504 を返すので1回だけ取り直す
    try {
      const r = await fetch(u, { headers: UA, signal: AbortSignal.timeout(15000) });
      if (r.status === 204) return [];                 // 該当なし
      if (!r.ok) { last = String(r.status); if (r.status < 500) break; continue; }
      const t = await r.text();
      return t.trim() ? JSON.parse(t) : [];
    } catch (e) { last = e.name || 'error'; }
  }
  throw new Error(last);
}

function hm(d) { return d.toISOString().slice(0, 16) + 'Z'; }

export const OPTIONS = preflight;

export async function GET(request) {
  const { H, url, deny } = check(request, overLimit);
  if (deny) return deny;

  const ids = [...new Set((url.searchParams.get('ids') || '').toUpperCase().split(','))]
    .map(s => s.trim()).filter(s => /^[A-Z0-9]{4}$/.test(s)).sort();
  if (!ids.length || ids.length > MAX_IDS) return json({ error: 'ids' }, 400, H);

  const now = Date.now();
  for (const [k, v] of cache) if (now - v.t > UP_TTL_MS) cache.delete(k);
  const ck = ids.join(',');
  const c = cache.get(ck);
  if (c) return new Response(c.body, { status: 200, headers: H });

  const base = 'https://aviationweather.gov/api/data/';
  const [mr, tr] = await Promise.allSettled([
    getJson(`${base}metar?ids=${ck}&format=json&hours=3`),
    getJson(`${base}taf?ids=${ck}&format=json`),
  ]);
  if (mr.status !== 'fulfilled')
    return json({ error: 'upstream', detail: [`METAR ${mr.reason && mr.reason.message}`] }, 502, H);

  const out = { updated: hm(new Date(now)), src: 'relay', m: {}, t: {} };
  const by = {};
  for (const x of mr.value) (by[x.icaoId] = by[x.icaoId] || []).push(x);
  for (const [icao, xs] of Object.entries(by)) {
    xs.sort((a, b) => (b.obsTime || 0) - (a.obsTime || 0));           // 新しい順
    const x = xs[0];
    out.m[icao] = {
      raw: x.rawOb || '', cat: x.fltCat || '', temp: x.temp, wdir: x.wdir, wspd: x.wspd,
      visib: x.visib, obs: x.obsTime,
      hist: xs.slice(1, 8).map(z => ({ obs: z.obsTime, raw: z.rawOb || '', cat: z.fltCat || '' })),
    };
  }
  if (tr.status === 'fulfilled') {
    for (const x of tr.value) {
      const prev = out.t[x.icaoId];
      const issue = x.issueTime ? Math.floor(Date.parse(x.issueTime) / 1000) : 0;
      if (prev && prev.issue >= issue) continue;                          // 最新の発表だけ残す
      out.t[x.icaoId] = { raw: x.rawTAF || '', issue, from: x.validTimeFrom, to: x.validTimeTo };
    }
  } else {
    out.tafErr = String(tr.reason && tr.reason.message);
  }
  const body = JSON.stringify(out);
  cache.set(ck, { t: now, body });
  return new Response(body, { status: 200, headers: H });
}
