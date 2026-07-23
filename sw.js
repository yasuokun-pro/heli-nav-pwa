/* HELI NAV Service Worker
   - アプリ本体(シェル)はインストール時にキャッシュ → オフラインでも起動
   - 地図タイル(地理院・OSM・RainViewer)は一度表示したものをキャッシュ
   ※ index.html 等を更新したら、下の VER を上げると全端末に更新が配信されます */
const VER = 'hnav-v6-37';
const TILE_CACHE = 'hnav-tiles';
const TILE_MAX = 4000; /* タイル保持枚数の上限(超えたら古いものから削除) */

const SHELL = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js',
  'https://cdn.jsdelivr.net/npm/leaflet-rotate@0.2.8/dist/leaflet-rotate.min.js'
];

const TILE_HOSTS = [
  'cyberjapandata.gsi.go.jp',
  'tile.openstreetmap.org',
  'tilecache.rainviewer.com'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(VER).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== VER && k !== TILE_CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

async function trimTiles() {
  try {
    const c = await caches.open(TILE_CACHE);
    const keys = await c.keys();
    if (keys.length > TILE_MAX) {
      for (let i = 0; i < 400 && i < keys.length; i++) await c.delete(keys[i]);
    }
  } catch (err) {}
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  /* 地図タイル: キャッシュ優先(オフライン時は事前表示した範囲が使える) */
  if (TILE_HOSTS.includes(url.host)) {
    e.respondWith(
      caches.open(TILE_CACHE).then(c =>
        c.match(req).then(hit => {
          if (hit) return hit;
          return fetch(req).then(res => {
            if (res.ok) { c.put(req, res.clone()); trimTiles(); }
            return res;
          });
        })
      )
    );
    return;
  }

  /* アプリ本体・CDN: キャッシュ優先 → なければネット → 最後はindexにフォールバック */
  e.respondWith(
    caches.match(req).then(hit => {
      if (hit) return hit;
      return fetch(req).then(res => {
        if (res.ok && (url.origin === self.location.origin || url.host === 'cdnjs.cloudflare.com')) {
          const copy = res.clone();
          caches.open(VER).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => (req.mode === 'navigate' ? caches.match('./index.html') : undefined));
    })
  );
});
