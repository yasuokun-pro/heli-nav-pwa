/* NOTAM中継 (Vercel Functions / Node.js ランタイム)
   ================================================
   取得元は**環境変数で切り替わる**。優先は SWIM → autorouter → FAA。

   S) SWIM デジタルノータムリクエストサービス(Web API・国交省 航空情報センター。2026-10-07 承認)
      env: SWIM_ID(SWIM ポータルのアカウントID=メール) / SWIM_PW / SWIM_LOGIN_URL / SWIM_SEARCH_URL
      ⚠ URL の途中(仕様書の公開版で「******」の部分)は**承認者にだけ通知される**。リポジトリに書かず env に置く。
      ⚠ 流れ: ログイン API に {"id","password"} を POST → Set-Cookie の MSMSI・MSMAI を保存 → 検索 API に Cookie を付けて GET。
        無通信・強制のセッションタイムアウトがある(時間は非公開)。403 なら1回だけログインし直して再試行。
      ⚠ 応答は {error_info, query, data:{totalCount, digitalNotam:[AIXM の XML 文字列…]}}。
        XML の event:textNOTAM/event:NOTAM から 番号・種別・Q コード・座標/半径・有効期間・E項 を拾う。
      ⚠ 日本の NOTAM の正式な出どころ。自衛隊飛行場・国内限定の通知もここに入る(EAD 由来の autorouter には来ないことがある)。

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

   POST /api/notam  本文 {"ids":"RJTT,RJAA,...","box":"s,w,n,e"(任意・SWIM のみ),"k":"合言葉"}
     → { updated, src:'swim'|'autorouter'|'faa', n:{ICAO:[{no,txt,from,to,iss,cls,type,q,lat,lon,rad,est,sch}]}, err:{ICAO:"理由"} }
     est=1 は終わりが見込み(EST)、sch は時間帯(D項)、lo/up は Q 行の下限/上限(FL)。SWIM のときだけ付く
     box があれば area:[同じ形の行] / areaInfo:{mode:'fir'|'split',trunc?,fail?,total,kept,days} / areaErr も返す(区域の NOTAM)
   ⚠ lat/lon/rad(NM) は**あるときだけ**。EADのNOTAMは大半が飛行場そのものへの通知で座標を持たない。
     アプリは座標があれば円、無ければ飛行場にピンを出す。
*/
import { check, preflight, json, makeLimiter } from '../lib/guard.js';

export const maxDuration = 45;    // 区域の分割取得で SWIM を最大28回引く(3本並列+失敗分の取り直し)
const UP_TTL_MS = 600_000;        // NOTAMは分単位で変わるものではないので10分使い回す
const MAX_IDS = 8;
const PAGE = 100;
// ⚠ 上流を叩く窓口なので、他より厳しめ(1分6回)にする
const overLimit = makeLimiter(6);
const cache = new Map();          // ids -> { t, body }
const PERM_AFTER = Date.now() / 1000 + 10 * 365 * 86400;   // これより先の終わりは PERM 扱い

const iso = (sec) => new Date(sec * 1000).toISOString();

/* ───────── SWIM(国交省 デジタルノータム) ───────── */
let swimCookie = null;            // 'MSMSI=…; MSMAI=…'
let swimLoginP = null;            // 並列の要求が同時にログインし直さないよう1本にまとめる
// used: 403 を返されたときに使っていた Cookie。他の要求が既にログインし直していればそれを使う
function swimRelogin(used) {
  if (swimCookie && swimCookie !== used) return Promise.resolve(swimCookie);
  if (!swimLoginP) swimLoginP = swimLogin().finally(() => { swimLoginP = null; });
  return swimLoginP;
}

async function swimLogin() {
  const r = await fetch(process.env.SWIM_LOGIN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ id: process.env.SWIM_ID, password: process.env.SWIM_PW }),
    redirect: 'manual',
    signal: AbortSignal.timeout(15000),
  });
  // Set-Cookie から MSMSI・MSMAI だけ取り出す(属性 Path/Secure などは捨てる)
  const raw = typeof r.headers.getSetCookie === 'function' ? r.headers.getSetCookie() : [r.headers.get('set-cookie') || ''];
  const jar = {};
  raw.join('\n').split(/\n|,(?=\s*MS)/).forEach(c => {
    const m = c.match(/^\s*(MSMSI|MSMAI)=([^;]*)/);
    if (m) jar[m[1]] = m[2];
  });
  if (!jar.MSMSI && !jar.MSMAI)
    throw new Error([400, 401, 403].includes(r.status) ? `SWIM のログインに失敗(${r.status}。ID・パスワードを確認)` : `SWIM login ${r.status}(Cookie なし)`);   // 誤りは 400 で返る(実測)
  swimCookie = Object.entries(jar).map(([k, v]) => `${k}=${v}`).join('; ');
  return swimCookie;
}

const ymdhm = d => d.toISOString().replace(/[-:T]/g, '').slice(0, 12);   // YYYYMMDDhhmm(UTC)
// YYMMDDhhmm → ISO。"PERM"・"…EST" はそのまま扱う
function swimTime(v) {
  const s = String(v || '').trim();
  if (!s) return '';
  if (/^PERM/i.test(s)) return 'PERM';
  const m = s.match(/^(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})/);
  if (!m) return s;
  return `20${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00Z`;          // 末尾の EST(終わりは見込み)は est で別に返す
}
function tag(xml, name) {
  const m = xml.match(new RegExp(`<event:${name}(?:\\s[^>]*)?>([\\s\\S]*?)</event:${name}>`));
  return m ? m[1].replace(/<!\[CDATA\[|\]\]>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').trim() : '';
}
// "3536N13946E" 形式(度分。秒つきもある)→ 10進
function swimCoord(s) {
  const m = String(s || '').match(/^(\d{2})(\d{2})(\d{2})?([NS])(\d{3})(\d{2})(\d{2})?([EW])$/);
  if (!m) return null;
  const lat = (+m[1] + m[2] / 60 + (m[3] ? m[3] / 3600 : 0)) * (m[4] === 'S' ? -1 : 1);
  const lon = (+m[5] + m[6] / 60 + (m[7] ? m[7] / 3600 : 0)) * (m[8] === 'W' ? -1 : 1);
  return { lat: +lat.toFixed(5), lon: +lon.toFixed(5) };
}
function swimRow(xml) {
  const i = xml.search(/<event:NOTAM[\s>]/);
  if (i < 0) return null;
  const n = xml.slice(i);
  const txt = tag(n, 'text');
  if (!txt) return null;
  const series = tag(n, 'series'), num = tag(n, 'number'), year = tag(n, 'year');
  const c = swimCoord(tag(n, 'coordinates')), rad = Number(tag(n, 'radius'));
  return {
    no: `${series}${String(num).padStart(4, '0')}/${String(year).slice(-2)}`,
    icao: tag(n, 'location'), txt,
    ...(c ? c : {}), ...(Number.isFinite(rad) && rad > 0 && rad < 999 ? { rad } : {}),
    iss: swimTime(tag(n, 'issued')), from: swimTime(tag(n, 'effectiveStart')), to: swimTime(tag(n, 'effectiveEnd')) || 'PERM',
    ...(/EST/i.test(tag(n, 'effectiveEnd')) ? { est: 1 } : {}),
    cls: tag(n, 'scope'), type: tag(n, 'type'), q: tag(n, 'selectionCode') ? `Q${tag(n, 'selectionCode')}` : '',
    ...(tag(n, 'schedule') ? { sch: tag(n, 'schedule') } : {}),
    ...(/^\d{3}$/.test(tag(n, 'minimumFL')) ? { lo: +tag(n, 'minimumFL') } : {}),
    ...(/^\d{3}$/.test(tag(n, 'maximumFL')) ? { up: +tag(n, 'maximumFL') } : {}),
  };
}
// 検索1回。cond は location / fir など。今から days 日の間に有効なもの
async function swimSearch(cond, days) {
  const now = new Date();
  const q = new URLSearchParams({
    userId: process.env.SWIM_ID, ...cond, display: '0',
    validDatetimeStart: ymdhm(now), validDatetimeEnd: ymdhm(new Date(now.getTime() + days * 86400e3)),
  });
  const url = `${process.env.SWIM_SEARCH_URL}?${q.toString().replace(/%20/g, '+')}`;
  const call = c => fetch(url, { headers: { Cookie: c, Accept: 'application/json' }, redirect: 'manual', signal: AbortSignal.timeout(20000) });
  const c0 = swimCookie || await swimRelogin(null);
  let r = await call(c0);
  if (r.status === 403 || r.status === 401 || (r.status >= 300 && r.status < 400)) r = await call(await swimRelogin(c0));   // セッション切れ
  if (!r.ok) throw new Error(`SWIM ${r.status}`);
  const raw = await r.text();
  let o;
  try { o = JSON.parse(raw); } catch { throw new Error(`SWIM 応答がJSONでない: ${raw.slice(0, 60).replace(/\s+/g, ' ')}`); }
  const e = o.error_info || {};
  // ⚠ error 1 は仕様書の表に無いが、**該当0件**のときに返る(2026-10-07 実機: 区域の分割取得で RD・RP(日本には無い)や
  //   WC・WF・WY など出ていない種類だけが error 1 になった)。失敗ではなく空として扱う
  if (String(e.error_code) === '1') return [];
  if (e.error_code && String(e.error_code) !== '0') {
    const err = new Error(`SWIM error ${e.error_code} ${e.error_description || ''}`.trim());
    err.code = String(e.error_code);
    throw err;
  }
  const d = Array.isArray(o.data) ? o.data[0] || {} : o.data || {};
  return [].concat(d.digitalNotam || []).map(x => swimRow(String(x))).filter(Boolean);
}
async function swimFetch(ids) {
  const rows = await swimSearch({ location: ids.join(' ') }, 7);
  const out = {};
  ids.forEach(i => { out[i] = []; });
  rows.forEach(v => { (out[v.icao] || (out[v.icao] = [])).push(v); });
  for (const k of Object.keys(out)) out[k].sort((a, b) => String(b.from).localeCompare(String(a.from)));
  return out;
}

/* ── 区域の NOTAM(v6-208) ──
   ⚠ 飛行場の名義(location)で引くだけだと、**FIR(RJJJ)名義の区域の通知**(無人機・空域制限・射撃・落下傘…)や、
     ルートから遠い飛行場の名義でもルートにかかる通知(羽田の名義で出る東京湾の区域など)が取れない。
   ⚠ SWIM の検索は場所(緯度経度)で絞れない。fir=RJJJ でまとめて引いて、**ここで外接矩形に当たるものだけ**残す。
     アプリは丸めた矩形(0.1度単位)しか送らない。ルートそのものとの距離はアプリが端末の中で見る。
   ⚠ 件数が検索上限を超えると error 14。そのときは種類ごとに分けて取り直す(下の swimArea) */
// 本文の座標 "354703N1391338E" / "3547N13913E"(区切りに空白・/ が入ることがある)
const TXT_COORD = /(\d{2})(\d{2})(\d{2}(?:\.\d+)?)?\s*([NS])\s*\/?\s*(\d{3})(\d{2})(\d{2}(?:\.\d+)?)?\s*([EW])/g;
function txtPts(t) {
  const o = [];
  for (const m of String(t || '').matchAll(TXT_COORD)) {
    const lat = (+m[1] + m[2] / 60 + (m[3] ? +m[3] / 3600 : 0)) * (m[4] === 'S' ? -1 : 1);
    const lon = (+m[5] + m[6] / 60 + (m[7] ? +m[7] / 3600 : 0)) * (m[8] === 'W' ? -1 : 1);
    if (lat >= 15 && lat <= 50 && lon >= 115 && lon <= 165) o.push([lat, lon]);
  }
  return o;
}
// 矩形 [s,w,n,e] に当たるか。本文に座標があればそれ(多角形・円の中心)、無ければ Q 行の円
function hitBox(v, b) {
  const pts = txtPts(v.txt);
  const m = 0.1;                                  // 線や円の縁が矩形のすぐ外にあるものも拾う
  if (pts.length) {
    const la = pts.map(p => p[0]), lo = pts.map(p => p[1]);
    const r = (v.rad && v.rad <= 100 ? v.rad : 5) / 60;
    return Math.min(...la) - r <= b[2] + m && Math.max(...la) + r >= b[0] - m &&
           Math.min(...lo) - r <= b[3] + m && Math.max(...lo) + r >= b[1] - m;
  }
  if (!Number.isFinite(v.lat) || !v.rad || v.rad > 100) return false;   // 999(FIR 全体)や座標なしは区域として描けない
  const r = v.rad / 60;
  return v.lat - r <= b[2] + m && v.lat + r >= b[0] - m && v.lon - r <= b[3] + m && v.lon + r >= b[1] - m;
}
// ⚠ fir=RJJJ 1回では検索上限(error 14)に当たった(2026-10-07 実機)。そのときは
//   ① location=RJJJ(FIR 名義は全種類) ② fir=RJJJ をノータムコードの主題(2文字)ごと: 航行警報 W*・空域制限 R*
//   に分けて引き直す。他の飛行場の名義の障害物・灯火などはここでは取らない(飛行場の欄で取る)
const AREA_SUBJ = ['WA', 'WB', 'WC', 'WD', 'WE', 'WF', 'WG', 'WH', 'WJ', 'WL', 'WM', 'WP', 'WR', 'WS', 'WT', 'WU', 'WV', 'WW', 'WY', 'WZ',
  'RA', 'RD', 'RM', 'RO', 'RP', 'RR', 'RT'];
async function pool(items, n, fn) {               // n 本ずつ並列(SWIM を一度に叩きすぎない)
  const out = new Array(items.length);
  let i = 0;
  await Promise.all(Array.from({ length: n }, async () => {
    while (i < items.length) { const k = i++; try { out[k] = { ok: await fn(items[k]) }; } catch (e) { out[k] = { e }; } }
  }));
  return out;
}
async function swimArea(box) {
  const days = 2;
  let rows, info;
  try {
    rows = await swimSearch({ fir: 'RJJJ' }, days);
    info = { mode: 'fir' };
  } catch (e) {
    if (e.code !== '14') throw e;
    const jobs = [{ location: 'RJJJ' }, ...AREA_SUBJ.map(c => ({ fir: 'RJJJ', notamCode: c }))];
    // ⚠ 7本並列では28種中11種が失敗した(2026-10-07 実機)。3本に減らし、失敗分は最後に1本ずつ取り直す
    const got = await pool(jobs, 3, c => swimSearch(c, days));
    for (let k = 0; k < jobs.length; k++) {
      if (got[k].e && got[k].e.code !== '14') {
        try { got[k] = { ok: await swimSearch(jobs[k], days) }; } catch (e) { got[k] = { e }; }
      }
    }
    const seen = new Set(), trunc = [], fail = [];
    rows = [];
    got.forEach((g, k) => {
      const name = jobs[k].notamCode || 'RJJJ名義';
      if (g.e) {
        if (g.e.code === '14') trunc.push(name);
        else fail.push(`${name}(${String(g.e.message || g.e).replace(/^SWIM /, '').slice(0, 40)})`);
        return;
      }
      g.ok.forEach(v => { const key = `${v.icao}|${v.no}`; if (!seen.has(key)) { seen.add(key); rows.push(v); } });
    });
    // Vercel のログで原因を追えるように(位置・矩形は出さない)
    if (trunc.length || fail.length) console.log(`swimArea split: rows=${rows.length} trunc=${trunc.join(',') || '-'} fail=${fail.join(' / ') || '-'}`);
    if (fail.length === jobs.length) throw got[0].e;
    info = { mode: 'split', ...(trunc.length ? { trunc } : {}), ...(fail.length ? { fail } : {}) };
  }
  const hit = rows.filter(v => hitBox(v, box));
  hit.sort((a, b) => String(b.from).localeCompare(String(a.from)));
  return { rows: hit, info: { ...info, total: rows.length, kept: hit.length, days } };
}

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
  const lat = Number(x.lat), lon = Number(x.lon), rad = Number(x.radius);
  return {
    no, icao: x.itema || '', txt,
    ...(Number.isFinite(lat) && Number.isFinite(lon) && (lat || lon) ? { lat, lon } : {}),
    ...(Number.isFinite(rad) && rad > 0 ? { rad } : {}),
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
  // GeoJSON の Point だけ拾う(Polygon は中心が出せないので地図には出さない)
  const g = p.geometry || {};
  const c = g.type === 'Point' && Array.isArray(g.coordinates) ? g.coordinates : null;
  return {
    no: n.number || n.id || '', icao: n.icaoLocation || n.location || '', txt,
    ...(c && Number.isFinite(+c[1]) && Number.isFinite(+c[0]) ? { lat: +c[1], lon: +c[0] } : {}),
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

  const sw = process.env.SWIM_ID && process.env.SWIM_PW && process.env.SWIM_LOGIN_URL && process.env.SWIM_SEARCH_URL;
  const ar = !sw && process.env.AR_USER && process.env.AR_PASS;
  const faa = !sw && !ar && process.env.FAA_CLIENT_ID && process.env.FAA_CLIENT_SECRET;
  if (!sw && !ar && !faa)
    return json({ error: 'key', detail: 'SWIM_*(または AR_USER / AR_PASS、FAA_CLIENT_ID / FAA_CLIENT_SECRET)が未設定' }, 503, H);

  const ids = [...new Set((p.get('ids') || '').toUpperCase().split(','))]
    .map(s => s.trim()).filter(s => /^[A-Z0-9]{4}$/.test(s)).sort();
  if (!ids.length || ids.length > MAX_IDS) return json({ error: 'ids' }, 400, H);

  // 区域の矩形 "s,w,n,e"(0.1度単位に丸めてある)。SWIM のときだけ使う
  const bx = String(p.get('box') || '').split(',').map(Number);
  const box = bx.length === 4 && bx.every(Number.isFinite) && bx[0] < bx[2] && bx[1] < bx[3] &&
    bx[2] - bx[0] <= 12 && bx[3] - bx[1] <= 15 ? bx.map(v => Math.round(v * 10) / 10) : null;

  const now = Date.now();
  for (const [k, v] of cache) if (now - v.t > UP_TTL_MS) cache.delete(k);
  const ck = (sw ? 'S:' : ar ? 'A:' : 'F:') + ids.join(',') + (sw && box ? '|' + box.join(',') : '');
  const hit = cache.get(ck);
  if (hit) return new Response(hit.body, { status: 200, headers: H });

  const out = { updated: new Date(now).toISOString().slice(0, 16) + 'Z', src: sw ? 'swim' : ar ? 'autorouter' : 'faa', n: {}, err: {} };
  if (sw) {
    const [a, b] = await Promise.allSettled([swimFetch(ids), box ? swimArea(box) : Promise.resolve(null)]);
    if (a.status === 'rejected') return json({ error: 'upstream', detail: String((a.reason && a.reason.message) || a.reason) }, 502, H);
    out.n = a.value;
    if (b.status === 'fulfilled' && b.value) { out.area = b.value.rows; out.areaInfo = b.value.info; }
    else if (b.status === 'rejected') out.areaErr = String((b.reason && b.reason.message) || b.reason);
  } else if (ar) {
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
