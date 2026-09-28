/* DIPS2.0(国交省 ドローン情報基盤システム)中継 (Vercel Functions / Node.js ランタイム)
   ================================================
   ドローンの飛行計画と飛行禁止エリア(緊急用務空域・有人機離発着エリア)を、**ログインした本人の画面にだけ**出すための中継。
   仕様: DIPS2.0 API(飛行計画通報)ガイドライン(ossportal.dips.mlit.go.jp/guide/fiss/)

   ⚠ **DIPS は接続元の固定IPしか受け付けない**(2026-09-28 無人航空機安全課の回答)。Vercel の送信元IPは固定されないので、
     DIPS 宛ての通信はすべて **固定IPを持つ VM(Oracle Cloud)の HTTPS プロキシ経由**で出す(`tools/dips-proxy/`)。
     プロキシは CONNECT で中継するだけで TLS は DIPS まで通しなので、**client_secret もトークンも VM からは見えない**。
   ⚠ 利用者は各自の DIPS アカウントでログインする(OIDC 認可コード)。client_secret はここ(環境変数)だけに置く。
   ⚠ **飛行計画の応答には通報者・操縦者の氏名・住所・電話・メール・保険が入っている**。ここで落として、
     範囲・時刻・高度・目的など安全に要る項目だけ返す。**サーバー側でキャッシュ・保存しない**(利用者ごとのトークンで取った他人の計画)。

   env:
     DIPS_ENV            'stg'(検証) か 'prod'(本番)。既定 stg
     DIPS_CLIENT_ID / DIPS_CLIENT_SECRET   申請後に航空局から通知される
     DIPS_REDIRECT       申請書に書いたログイン後のリダイレクトURL(完全一致が要る)
     DIPS_PROXY          https://ユーザー:パスワード@固定IP:ポート
     DIPS_PROXY_CA       プロキシの自己署名証明書(PEM)。これで相手が本当に自分の VM か確かめる
   どれかが欠けていれば 503 {"error":"key"}。

   POST /api/dips  本文 {"op":..., "k":"合言葉", ...}
     op=cfg                              → { env, authUrl, clientId, redirect }  (ログイン画面のURLをアプリが組み立てる用)
     op=token   code                     → { at, atExp, rt, rtExp }
     op=refresh rt                       → 同上
     op=plans   at lat lon r(NM) [from to: 'yyyyMMdd HHmm' JST]   → { n, plans:[...] }
     op=areas   at lat lon r(NM) [from to]                          → { n, areas:[...] }
*/
import { fetch, ProxyAgent } from 'undici';   // ⚠ Node 内蔵の fetch に外の undici の dispatcher を渡すと版違いで落ちる
import { check, preflight, json, makeLimiter } from '../lib/guard.js';

const overLimit = makeLimiter(20);
const EP = {
  stg:  { auth: 'https://www.stg.uafp.dips.mlit.go.jp/auth/realms/drs-fpl', api: 'https://www.stg.uafpi.dips.mlit.go.jp/api' },
  prod: { auth: 'https://www.dips-reg.mlit.go.jp/auth/realms/drs-fpl',      api: 'https://www.uafpi.dips.mlit.go.jp/api' },
};
const MAX_R_M = 50_000;          // 検索半径の上限(約27NM)。広すぎる検索は DIPS に負担をかける
const MAX_ROWS = 300;

let agent = null, agentKey = '';
function proxy() {
  const key = process.env.DIPS_PROXY + '|' + (process.env.DIPS_PROXY_CA || '').length;
  if (agent && agentKey === key) return agent;
  const u = new URL(process.env.DIPS_PROXY);
  const token = 'Basic ' + Buffer.from(decodeURIComponent(u.username) + ':' + decodeURIComponent(u.password)).toString('base64');
  u.username = ''; u.password = '';
  agent = new ProxyAgent({
    uri: u.toString(), token,
    // ⚠ プロキシの証明書は自己署名。CA として渡して検証する(rejectUnauthorized は外さない)。
    //   Node は IP アドレスを TLS の servername にできないので、証明書は名前 'dips-proxy' で作ってそれで照合する
    proxyTls: { ca: process.env.DIPS_PROXY_CA, servername: 'dips-proxy' },
  });
  agentKey = key;
  return agent;
}
const dfetch = (url, init) => fetch(url, { ...init, dispatcher: proxy(), signal: AbortSignal.timeout(20000) });

function env() {
  const e = process.env.DIPS_ENV === 'prod' ? 'prod' : 'stg';
  const ok = process.env.DIPS_CLIENT_ID && process.env.DIPS_CLIENT_SECRET && process.env.DIPS_REDIRECT
    && process.env.DIPS_PROXY && process.env.DIPS_PROXY_CA;
  return ok ? { e, ...EP[e] } : null;
}

/* ───── トークン ───── */
function b64json(s) {
  try { return JSON.parse(Buffer.from(s.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8')); }
  catch (e) { return null; }
}
async function tokenCall(E, params) {
  const r = await dfetch(`${E.auth}/protocol/openid-connect/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
    body: new URLSearchParams({ ...params, client_id: process.env.DIPS_CLIENT_ID, client_secret: process.env.DIPS_CLIENT_SECRET }),
  });
  const o = await r.json().catch(() => ({}));
  if (!r.ok || !o.access_token) {
    // invalid_grant = 認可コードの使い回し・リフレッシュトークン切れ → アプリはログインし直す
    const e = new Error(o.error || `token ${r.status}`); e.relogin = o.error === 'invalid_grant'; throw e;
  }
  // ID トークンの検証(仕様書 2.3.4(2))。トークン窓口から TLS で直接受け取っているので署名は見ない(OIDC Core 3.1.3.7)
  if (o.id_token) {
    const p = b64json(o.id_token.split('.')[1] || '');
    const now = Date.now() / 1000;
    if (!p || p.iss !== E.auth || ![].concat(p.aud).includes(process.env.DIPS_CLIENT_ID) || !(p.exp > now))
      throw new Error('id_token の検証に失敗');
  }
  const now = Date.now();
  return {
    at: o.access_token, atExp: now + (o.expires_in || 300) * 1000,
    rt: o.refresh_token, rtExp: o.refresh_expires_in ? now + o.refresh_expires_in * 1000 : 0,   // 0 = 期限なし(offline)
  };
}

/* ───── 検索 ───── */
const PURPOSE = ['', '空撮', '報道取材', '警備', '農林水産業', '測量', '環境調査', '設備メンテナンス', 'インフラ点検・保守',
  '資材管理', '輸送・宅配', '自然観測', '事故・災害対応等', 'その他(業務)', '趣味', '研究開発', 'その他(業務以外)'];
const AREA_TYPE = { 1: '空港等の周辺空域', 2: '人口集中地区', 5: 'レッドゾーン', 6: 'イエローゾーン', 7: '条例等のエリア',
  8: '有人機離発着エリア', 9: '緊急用務空域', 10: 'その他1', 11: 'その他2' };

function geo(g) {
  if (!g) return null;
  if (g.type === 'Circle' && Array.isArray(g.center))
    return { c: [+g.center[1], +g.center[0]], r: +g.radius || 0 };                      // [lat,lon] と半径m
  if (g.type === 'Polygon' && Array.isArray(g.coordinates))
    return { p: g.coordinates.map(x => [+x[1], +x[0]]).filter(x => Number.isFinite(x[0]) && Number.isFinite(x[1])) };
  return null;
}
/* ⚠ ここで返す項目だけがアプリに渡る。氏名・住所・電話・メール・保険・技能証明・機体登録は**入れない** */
function planRow(x) {
  const g = geo(x.flyRoute);
  if (!g) return null;
  return {
    id: String(x.flightPlanId || ''),
    nm: String(x.name || '').slice(0, 80),
    pur: [].concat(x.flightPurpose || []).map(n => PURPOSE[n] || '').filter(Boolean),
    asp: [].concat(x.flightAirspace || []).map(Number),       // 1 DID上空 2 150m以上 3 空港周辺
    typ: [].concat(x.flightType || []).map(Number),           // 3 夜間 4 目視外 など
    from: x.startTime || '', to: x.finishTime || '',
    altM: Number(x.flightAltitude) || null,                   // 地表からの高さ(m)
    kmh: Number(x.flightSpeed) || null,
    dep: String(x.departurePoint || '').slice(0, 60), dst: String(x.destinationPoint || '').slice(0, 60),
    moor: x.exceptionalConditionsMooring === '1' ? 1 : 0,     // 係留飛行
    ...g,
  };
}
function areaRow(x) {
  const r = x.range || {};
  const g = geo(r);
  if (!g) return null;
  const t = Number(x.flightProhibitedAreaTypeId);
  return { id: String(x.flightProhibitedAreaId || ''), nm: String(x.name || '').slice(0, 80), t, tn: AREA_TYPE[t] || '',
    from: x.startTime || '', to: x.finishTime || '', url: /^https:\/\//.test(x.url || '') ? x.url : '', ...g };
}

const T = /^\d{8} \d{4}$/;
function searchBody(p) {
  const lat = +p.get('lat'), lon = +p.get('lon'), rNM = +p.get('r');
  if (!(lat > 20 && lat < 46 && lon > 122 && lon < 154 && rNM > 0)) return null;
  const b = { features: { type: 'Circle', center: [lon, lat], radius: Math.min(MAX_R_M, Math.round(rNM * 1852)) } };
  const from = p.get('from'), to = p.get('to');
  if (from && T.test(from)) b.startTime = from;
  if (to && T.test(to)) b.finishTime = to;
  return b;
}
async function apiCall(E, path, at, body) {
  const r = await dfetch(`${E.api}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${at}`, 'Content-Type': 'application/json;charset=UTF-8' },
    body: JSON.stringify(body),
  });
  if (r.status === 401) { const e = new Error('expired'); e.expired = true; throw e; }
  if (!r.ok) throw new Error(`DIPS ${r.status}`);
  return r.json();
}

export const OPTIONS = preflight;
export async function POST(request) {
  const { H, p, deny } = await check(request, overLimit, 8000);    // トークン(JWT)が長いので本文の上限を広げる
  if (deny) return deny;
  const E = env();
  if (!E) return json({ error: 'key', detail: 'DIPS_* の環境変数が未設定' }, 503, H);
  const op = p.get('op');
  try {
    if (op === 'cfg')
      return json({ env: E.e, authUrl: `${E.auth}/protocol/openid-connect/auth`, clientId: process.env.DIPS_CLIENT_ID,
        redirect: process.env.DIPS_REDIRECT }, 200, H);
    if (op === 'token') {
      const code = p.get('code');
      if (!code || code.length > 2000) return json({ error: 'code' }, 400, H);
      return json(await tokenCall(E, { grant_type: 'authorization_code', code, redirect_uri: process.env.DIPS_REDIRECT }), 200, H);
    }
    if (op === 'refresh') {
      const rt = p.get('rt');
      if (!rt) return json({ error: 'rt' }, 400, H);
      return json(await tokenCall(E, { grant_type: 'refresh_token', refresh_token: rt }), 200, H);
    }
    if (op === 'plans' || op === 'areas') {
      const at = p.get('at'), b = searchBody(p);
      if (!at || !b) return json({ error: 'args' }, 400, H);
      if (op === 'plans') {
        const o = await apiCall(E, '/flight-plan/search', at, { ...b, allFlightPlan: '0' });
        const rows = [].concat(o.flightPlanInfo || []).map(planRow).filter(Boolean);
        return json({ n: o.totalCount ?? rows.length, plans: rows.slice(0, MAX_ROWS) }, 200, H);
      }
      // 空港周辺・DID・レッド/イエローゾーンはアプリの既存レイヤーと重なるので、ヘリに効く 8 と 9 だけ取る
      const { startTime, finishTime, ...geoOnly } = b;
      const o = await apiCall(E, '/flight-prohibited-area/search', at,
        { ...geoOnly, flightProhibitedAreaInfo: { flightProhibitedAreaTypeId: [8, 9], ...(startTime ? { startTime } : {}),
          ...(finishTime ? { finishTime } : {}) } });
      const rows = [].concat(o.flightProhibitedAreaInfo || []).map(areaRow).filter(Boolean);
      return json({ n: o.totalCount ?? rows.length, areas: rows.slice(0, MAX_ROWS) }, 200, H);
    }
    return json({ error: 'op' }, 400, H);
  } catch (e) {
    if (e.expired) return json({ error: 'expired' }, 401, H);          // アクセストークン切れ → アプリが refresh してやり直す
    if (e.relogin) return json({ error: 'relogin' }, 401, H);          // リフレッシュも切れた → ログインし直し
    // プロキシで止まったとき(407=合言葉違い・403=宛先が許可外・接続不可=VM停止)は cause に理由が入る
    const c = e && e.cause, why = c ? `: ${c.code || ''} ${c.message || ''}`.trim() : '';
    return json({ error: 'upstream', detail: String((e && e.message) || e) + why }, 502, H);
  }
}
