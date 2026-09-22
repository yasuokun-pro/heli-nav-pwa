/* NOTAM中継 (Vercel Functions / Node.js ランタイム)
   ================================================
   取得元は**環境変数で切り替わる**。両方入っていれば autorouter を使う。

   A) autorouter.aero (既定) … Eurocontrol EAD(INO)由来。世界中のNOTAMが入っている。
      env: AR_USER(アカウントのメール) / AR_PASS(そのアカウントのパスワード)
      ⚠ autorouter の client_credentials は **client_id=メール・client_secret=パスワード** という作り。
        つまり**アカウントのパスワードそのもの**を預けることになるので、
        **autorouter 専用の、他では使っていないパスワード**にすること。
      ⚠⚠ **autorouter の規約で、APIの利用には「API usage agreement」が要る**
        ("Use of autorouter's API ... is prohibited unless an API usage agreement is in place")。
        先に許可を取ること。**許可が無いうちは AR_USER / AR_PASS を設定しない**(設定しなければこの窓口は503を返す)。
      ⚠ トークンは1時間で切れる。ここでは55分で取り直し、401なら1回だけ取り直して再試行する。
        1アカウントで同時に有効なトークンは20個まで。無駄に取らないこと。
      ⚠ itemas に **複数のICAOをまとめて**渡せるので、上流は1回で済む。

   B) FAA NOTAM API … env: FAA_CLIENT_ID / FAA_CLIENT_SECRET
      ⚠ 2026-09時点、FAAのポータルは login.gov の**身元確認(米国発行の身分証)**を要求するようになり、
        日本から鍵を取るのは現実的でない。コードは残してあるので鍵が手に入れば使える。
      ⚠ こちらは1回の要求で飛行場1つ。ids の数だけ並列に投げる。

   ⚠ **公式ブリーフィングの代わりにはならない**。日本の正式な情報源は AIS Japan / 部隊のブリーフィング。
     取れなかったことを「異常なし」と読まないこと。

   POST /api/notam  本文 {"ids":"RJTT,RJAA,...","k":"合言葉"}
     → { updated, src:'autorouter'|'faa', n:{ICAO:[{no,txt,from,to,iss,cls,type,q}]}, err:{ICAO:"理由"} }
*/
import { check, preflight, json, makeLimiter } from '../lib/guard.js';

const UP_TTL_MS = 600_000;        // NOTAMは分単位で変わるものではないので10分使い回す
const MAX_IDS = 8;
const PAGE = 100;
// ⚠ 上流を叩く窓口なので、他より厳しめ(1分6回)にする
const overLimit = makeLimiter(6);
const cache = new Map();          // ids -> { t, body }
const PERM_AFTER = Date.now() / 1000 + 10 * 365 * 86400;   // これより先の終わりは PERM 扱い

const iso = (sec) => new Date(sec * 1000).toISOString();

/* ───────── autorouter ───────── */
let tok = null;                   // { v, exp }

async function arToken(force) {
  if (!force && tok && Date.now() < tok.exp) return tok.v;
  const r = await fetch('https://api.autorouter.aero/v1.0/oauth2/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'client_credentials',
      client_id: process.env.AR_USER,
      client_secret: process.env.AR_PASS,
    }),
    signal: AbortSignal.timeout(15000),
  });
  if (!r.ok) throw new Error(r.status === 401 || r.status === 403
    ? 'autorouter の認証に失敗(メール・パスワード・API利用の設定を確認)' : `autorouter token ${r.status}`);
  const o = await r.json();
  if (!o.access_token) throw new Error('autorouter token なし');
  // 有効期限より少し手前で取り直す(既定は1時間なので55分)
  tok = { v: o.access_token, exp: Date.now() + Math.max(60, (o.expires_in || 3600) - 300) * 1000 };
  return tok.v;
}

function arRow(x) {
  const txt = (x.iteme || '').trim();
  if (!txt) return null;
  const no = `${x.series || ''}${String(x.number || '').padStart(4, '0')}/${String(x.year || '').slice(-2)}`;
  const end = Number(x.endvalidity) || 0;
  return {
    no, icao: x.itema || '', txt,
    iss: '',                                        // autorouter は発行時刻を返さない
    from: x.startvalidity ? iso(x.startvalidity) : '',
    to: !end || end > PERM_AFTER ? 'PERM' : iso(end),
    cls: x.scope || '',                             // A(飛行場) E(航空路) W(警告) など
    type: x.type || '',                             // N / R / C
    q: x.code23 || x.code45 ? `Q${x.code23 || ''}${x.code45 || ''}` : '',
  };
}

async function arFetch(ids) {
  const now = Math.floor(Date.now() / 1000);
  const u = 'https://api.autorouter.aero/v1.0/notam'
    + `?itemas=${encodeURIComponent(JSON.stringify(ids))}`
    + `&offset=0&limit=${PAGE}&startvalidity=0&endvalidity=${2 ** 32 - 1}`;
  const call = async (t) => fetch(u, {
    headers: { Authorization: `Bearer ${t}`, Accept: 'application/json' },
    signal: AbortSignal.timeout(20000),
  });
  let r = await call(await arToken(false));
  if (r.status === 401) r = await call(await arToken(true));     // 切れていたら取り直して1回だけ再試行
  if (!r.ok) throw new Error(`autorouter ${r.status}`);
  const o = await r.json();
  const rows = Array.isArray(o.rows) ? o.rows : [];
  const out = {};
  ids.forEach(i => { out[i] = []; });
  rows.forEach(x => {
    const v = arRow(x);
    if (!v) return;
    // 終わった分と、まだ有効でない遠い先の分は落とす
    if (Number(x.endvalidity) && Number(x.endvalidity) < now) return;
    (out[v.icao] || (out[v.icao] = [])).push(v);
  });
  for (const k of Object.keys(out)) out[k].sort((a, b) => String(b.from).localeCompare(String(a.from)));
  return out;
}

/* ───────── FAA(鍵が手に入ったとき用) ───────── */
function faaRow(it) {
  const p = (it && it.properties) || {};
  const core = p.coreNOTAMData || {};
  const n = core.notam || {};
  const tr = (core.notamTranslation || []).find(x => x && (x.simpleText || x.formattedText)) || {};
  const txt = (n.text || tr.simpleText || tr.formattedText || '').trim();
  if (!txt) return null;
  return {
    no: n.number || n.id || '', icao: n.icaoLocation || n.location || '', txt,
    iss: n.issued || '', from: n.effectiveStart || '', to: n.effectiveEnd || '',
    cls: n.classification || '', type: n.type || '', q: n.selectionCode || '',
  };
}

async function faaFetch(icao, id, secret) {
  const u = 'https://external-api.faa.gov/notamapi/v1/notams'
    + `?icaoLocation=${icao}&responseFormat=geoJson&pageSize=50&pageNum=1`
    + '&sortBy=effectiveStartDate&sortOrder=Desc';
  const r = await fetch(u, {
    headers: { client_id: id, client_secret: secret, Accept: 'application/json' },
    signal: AbortSignal.timeout(15000),
  });
  if (!r.ok) throw new Error(r.status === 401 || r.status === 403 ? '鍵が違う' : `上流 ${r.status}`);
  const o = await r.json();
  return (Array.isArray(o.items) ? o.items : []).map(faaRow).filter(Boolean);
}

export const OPTIONS = preflight;
export const POST = (request) => GET(request);

export async function GET(request) {
  const { H, p, deny } = await check(request, overLimit);
  if (deny) return deny;

  const ar = process.env.AR_USER && process.env.AR_PASS;
  const faa = process.env.FAA_CLIENT_ID && process.env.FAA_CLIENT_SECRET;
  if (!ar && !faa)
    return json({ error: 'key', detail: 'AR_USER / AR_PASS(または FAA_CLIENT_ID / FAA_CLIENT_SECRET)が未設定' }, 503, H);

  const ids = [...new Set((p.get('ids') || '').toUpperCase().split(','))]
    .map(s => s.trim()).filter(s => /^[A-Z0-9]{4}$/.test(s)).sort();
  if (!ids.length || ids.length > MAX_IDS) return json({ error: 'ids' }, 400, H);

  const now = Date.now();
  for (const [k, v] of cache) if (now - v.t > UP_TTL_MS) cache.delete(k);
  const ck = (ar ? 'A:' : 'F:') + ids.join(',');
  const hit = cache.get(ck);
  if (hit) return new Response(hit.body, { status: 200, headers: H });

  const out = { updated: new Date(now).toISOString().slice(0, 16) + 'Z', src: ar ? 'autorouter' : 'faa', n: {}, err: {} };
  if (ar) {
    try { out.n = await arFetch(ids); }
    catch (e) { return json({ error: 'upstream', detail: String((e && e.message) || e) }, 502, H); }
  } else {
    const got = await Promise.allSettled(ids.map(i => faaFetch(i, process.env.FAA_CLIENT_ID, process.env.FAA_CLIENT_SECRET)));
    got.forEach((g, i) => {
      if (g.status === 'fulfilled') out.n[ids[i]] = g.value;
      else out.err[ids[i]] = String((g.reason && g.reason.message) || g.reason);
    });
    if (!Object.keys(out.n).length) return json({ error: 'upstream', detail: out.err }, 502, H);
  }
  const body = JSON.stringify(out);
  cache.set(ck, { t: now, body });
  return new Response(body, { status: 200, headers: H });
}
