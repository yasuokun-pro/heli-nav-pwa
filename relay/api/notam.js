/* NOTAM中継 (Vercel Functions / Node.js ランタイム)
   ================================================
   取得元: FAA NOTAM API  https://external-api.faa.gov/notamapi/v1/notams
     ・api.faa.gov の無料登録で出る client_id / client_secret をヘッダで送る。
       **Vercel の環境変数 FAA_CLIENT_ID / FAA_CLIENT_SECRET に入れる**(リポジトリには絶対に書かない)。
     ・米国のAPIだが、ICAO経由で流れてくる**日本の飛行場のNOTAMも引ける**(location=RJTTなど)。
   ⚠ **公式ブリーフィングの代わりにはならない**。日本の正式な情報源は AIS Japan / 部隊のブリーフィング。
     自衛隊飛行場や国内限定の通知は流れてこないことがある。取れなかったことを「異常なし」と読まないこと。
   ⚠ 1回の要求で**飛行場1つ**しか指定できないので、ids の数だけ並列に投げる(MAX_IDS で上限)。
   ⚠ 鍵が未設定なら 503 と {error:'key'} を返す(アプリはその旨を出す)。上流の失敗は空で返さず err に理由を入れる。

   POST /api/notam  本文 {"ids":"RJTT,RJAA,...","k":"合言葉"}
     → { updated, src:'relay', n:{ICAO:[{no,txt,from,to,iss,cls,type,q}]}, err:{ICAO:"理由"} }
*/
import { check, preflight, json, makeLimiter } from '../lib/guard.js';

const UP_TTL_MS = 600_000;        // NOTAMは分単位で変わるものではないので10分使い回す
const MAX_IDS = 8;
// ⚠ 1回で最大8本も上流を叩くので、他より厳しめ(1分6回)にする
const overLimit = makeLimiter(6);
const PAGE = 50;                  // 1飛行場あたりの上限。多い空港でも通常これで足りる
const cache = new Map();          // ids -> { t, body }

/* 形が変わっても落ちないように、あるものだけ拾う */
function pick(it) {
  const p = (it && it.properties) || {};
  const core = p.coreNOTAMData || {};
  const n = core.notam || {};
  const tr = (core.notamTranslation || []).find(x => x && (x.simpleText || x.formattedText)) || {};
  const txt = (n.text || tr.simpleText || tr.formattedText || '').trim();
  if (!txt) return null;
  return {
    no: n.number || n.id || '',
    icao: n.icaoLocation || n.location || '',
    txt,
    iss: n.issued || '',
    from: n.effectiveStart || '',
    to: n.effectiveEnd || '',           // 'PERM' が入ることがある
    cls: n.classification || '',        // INTL / MIL / DOM / LMIL / FDC
    type: n.type || '',                 // N(new) R(replace) C(cancel)
    q: n.selectionCode || '',           // QMRLC などのQコード
  };
}

async function fetchOne(icao, id, secret) {
  const u = `https://external-api.faa.gov/notamapi/v1/notams`
    + `?icaoLocation=${icao}&responseFormat=geoJson&pageSize=${PAGE}&pageNum=1&sortBy=effectiveStartDate&sortOrder=Desc`;
  const r = await fetch(u, {
    headers: { client_id: id, client_secret: secret, Accept: 'application/json' },
    signal: AbortSignal.timeout(15000),
  });
  if (!r.ok) throw new Error(r.status === 401 || r.status === 403 ? '鍵が違う' : `上流 ${r.status}`);
  const o = await r.json();
  const items = Array.isArray(o.items) ? o.items : [];
  return items.map(pick).filter(Boolean);
}

export const OPTIONS = preflight;
export const POST = (request) => GET(request);

export async function GET(request) {
  const { H, p, deny } = await check(request, overLimit);
  if (deny) return deny;

  const id = process.env.FAA_CLIENT_ID, secret = process.env.FAA_CLIENT_SECRET;
  if (!id || !secret)
    return json({ error: 'key', detail: 'FAA_CLIENT_ID / FAA_CLIENT_SECRET が未設定' }, 503, H);

  const ids = [...new Set((p.get('ids') || '').toUpperCase().split(','))]
    .map(s => s.trim()).filter(s => /^[A-Z0-9]{4}$/.test(s)).sort();
  if (!ids.length || ids.length > MAX_IDS) return json({ error: 'ids' }, 400, H);

  const now = Date.now();
  for (const [k, v] of cache) if (now - v.t > UP_TTL_MS) cache.delete(k);
  const ck = ids.join(',');
  const hit = cache.get(ck);
  if (hit) return new Response(hit.body, { status: 200, headers: H });

  const got = await Promise.allSettled(ids.map(i => fetchOne(i, id, secret)));
  const out = { updated: new Date(now).toISOString().slice(0, 16) + 'Z', src: 'relay', n: {}, err: {} };
  got.forEach((g, i) => {
    if (g.status === 'fulfilled') out.n[ids[i]] = g.value;
    else out.err[ids[i]] = String((g.reason && g.reason.message) || g.reason);
  });
  // ⚠ 全部だめなら 502。一部だけ取れたときは取れた分を返し、残りを err に載せる
  if (!Object.keys(out.n).length)
    return json({ error: 'upstream', detail: out.err }, 502, H);
  const body = JSON.stringify(out);
  cache.set(ck, { t: now, body });
  return new Response(body, { status: 200, headers: H });
}
