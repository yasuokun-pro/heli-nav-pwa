# HELI NAV 引き継ぎ資料(Claude Code向け)

最終更新: 2026-07-08 / 現行バージョン: v6(PWA)

---

## 1. プロジェクト概要

ヘリコプター運航者(プロの操縦士)個人が業務補助に使うナビゲーションPWA。
Claude.aiのチャット上でv1→v6まで反復開発してきたものを、以後Claude Codeで継続開発する。

**設計方針(必ず維持すること)**
- 依存最小の単一HTML構成(ビルド不要、GitHub Pagesに置くだけで動く)
- 無料・APIキー不要のデータソースを優先
- アビオニクス風ダークUI(配色・フォントは CSS変数で統一)
- 参考情報である旨のディスクレーマーをfooterから消さない
  (正式な航法情報源ではない/AIP・最新チャートで要確認)

## 2. ファイル構成

```
heli-nav-pwa/
├─ index.html    … アプリ本体(HTML+CSS+JS全部入り、約900行)
├─ sw.js         … Service Worker(オフラインキャッシュ)
├─ manifest.json … PWAマニフェスト
├─ icon-192.png / icon-512.png
└─ README.md     … GitHub Pages公開・インストール手順(ユーザー向け)
```

デプロイ: GitHub Pages(main / root)。**index.html等を変更したら sw.js 先頭の
`const VER = 'hnav-v6-1'` を必ずインクリメント**(しないと既存端末に更新が届かない)。

## 3. 技術スタック

| 用途 | 採用 | 備考 |
|---|---|---|
| 地図 | Leaflet 1.9.4 (cdnjs) | プラグインなし素のLeaflet |
| ベースタイル | 国土地理院 淡色(pale)/ 全国最新写真(seamlessphoto)/ OSM | 3段トグル。無料・キー不要 |
| 雨雲 | RainViewer タイル | §6参照 |
| 他機(ADS-B) | OpenSky Network REST | 失敗時デモデータにフォールバック |
| フォント | IBM Plex Mono(データ表示)/ Noto Sans JP(UI) | Google Fonts。オフライン時はシステムフォントに劣化 |
| 保存 | localStorage | sandboxed iframe等で例外が出る環境向けにtry/catchラッパー(`store`)経由 |

Googleマップは**不採用**(要APIキー・従量課金。2025/3改定で$200クレジット廃止、
Maps JS APIは月1万ロードまで無料)。ユーザーは当面地理院タイルで了承済み。

## 4. 機能一覧と実装箇所(index.html内の目印コメント)

| 機能 | 実装 | 主な関数/変数 |
|---|---|---|
| ポイント登録 | 地図タップ→マゼンタ経路線。ドラッグ・改名・削除可 | `addWp()` `wps[]` `redraw()` |
| 航法計算 | 区間ごとMC/MH(WCA)/GS/ETE/燃料+合計行 | `trueBrg()` `magOf()` `windTri()` |
| 風三角 | TAS+風向(°T)+風速→WCA・TH・GS | `windTri()` §5参照 |
| 燃料計算 | FF/FOB→必要燃料・着陸時残(30分切りで赤)・Endurance | `redraw()`内 |
| Direct-To | WP/飛行場へ第2コース(シアン破線)。元ルート保持 | `setDct()` `updateDct()` `dctTarget` |
| GPS | watchPositionで自機位置+実測GS(kt) | `gpsWatch` `ownPos` `ownSpdKt` |
| 実GS連動 | LIVEトグルON+速度取得時、ETE/燃料を実測GSで再計算 | `liveGsActive()` `effGs()` |
| 飛行ログ | 離陸/着陸ボタン→OFF/ON/飛行時間/経路を記録、CSV出力 | `logs[]` `saveLogs()` |
| 共有 | 共有コード(HNAV1.base64)/JSON/GPX書出・読込 | `routeObj()` `loadRouteObj()` |
| 空域(暫定) | 管制圏=青実線円・情報圏=アンバー破線円(概略、既定半径9km) | `ASP[]` `aspLayer` |
| 飛行場情報 | ✈トグル→ICAOマーカー→ポップアップ(種別/標高/滑走路/座標)+D→/ルート追加 | `apLayer` |
| 永続化 | ルート・設定・ログ・ベース地図選択を自動保存/起動時復元 | `store` `saveState()` `init()` |

## 5. 計算仕様(変更時は要注意)

- 距離: haversine、地球半径 `R_NM=3440.065`(NM)
- 真方位: 大圏初期方位 `trueBrg()`
- **磁方位 = 真方位 + 西偏差**(`varW`、手入力、初期値8°W)。
  日本は全域西偏(概ね5〜11°W)なので加算方向で正しい。東偏対応は未実装(負値入力で代用可)
- 風三角(`windTri(tc)`、風向は「吹いてくる」**真方位**):
  - `rel = wd − tc`、横風 `xw = ws·sin(rel)`(+は右から)、向い風 `hw = ws·cos(rel)`
  - `WCA = asin(xw/TAS)`(風上へ修正、右風なら+)
  - `TH = TC + WCA`、`GS = TAS·cos(WCA) − hw`
  - `|xw|≥TAS` または `GS≤0` は `{bad:true}` → UIは「不可」表示
- 実測GS: `p.coords.speed`(m/s)×1.9438。null(静止・非対応端末)なら計画値へ自動フォールバック。有効条件は `>2kt`
- ETE表示 `fmtHM`(h:mm)、方位表示 `fmt3`(3桁、000は360)
- 燃料残警告: 着陸時予測残 < FF×0.5(=30分)で赤

## 6. 外部API・データソースの注意点

- **RainViewer**: 正攻法は `api.rainviewer.com/public/weather-maps.json` から最新タイムスタンプ取得。
  fetchがCSP等で失敗する環境向けに `floor(now/600)*600−600` で推定するフォールバックあり(`rainTs()`)。
  国内精度重視なら気象庁ナウキャストタイルへの置換を検討(basetime取得のJSONが必要)
- **OpenSky**: 匿名利用はレート制限が厳しい(数十秒間隔)。地図のbboxでクエリ。
  失敗・0件時はデモ4機を表示し「DEMO」タグ明示。**ADS-B/モードS搭載機しか映らない**旨をUIに残すこと。
  本格運用ならOpenSkyアカウント認証 or ADS-B Exchange(有料)検討
- **地理院タイル**: 出典表記(attribution)必須。淡色 `xyz/pale/{z}/{x}/{y}.png`、
  写真 `xyz/seamlessphoto/{z}/{x}/{y}.jpg`
- Claude.aiのアーティファクトプレビュー内では外部fetch/geolocation/localStorage/SWが
  制限されることがある(全てtry/catchでフォールバック済み)。**本番評価はGitHub Pages上で行う**

## 7. データモデル

```js
// waypoint(メモリ上)
{name:'WP1', lat:35.5, lng:139.7, marker:<Leaflet Marker>, isWp:true}

// 共有コード = 'HNAV1.' + base64(JSON):
{v:1,
 set:{tas,wDir,wSpd,varW,ff,fob},
 wp:[[lat,lng,'名称'], ...]}

// 飛行ログ(logs[] / localStorage 'hnav.logs')
{date:'2026/7/8', off:'09:12', on:'10:03', dur:'00:51', route:'WP1→WP2'}

// 空域・飛行場マスタ ASP[](現在は同一配列で兼用)
{n:'東京(羽田)', icao:'RJTT', t:'ctr'|'inf', lat, lng,
 r?:半径km(既定9), elev?:ft, rwy?:'文字列'}

// localStorageキー
'hnav.route' / 'hnav.logs' / 'hnav.base'(ベース地図index)
```

## 8. 最優先タスク: AIP空域ポリゴン化(進行中)

**背景**: 現在の空域表示は「主要空港に半径9km(八尾のみ5km)の円」という概略。
実際の管制圏・情報圏・進入管制区・訓練/試験空域の境界とは異なる。

**確定済みの進め方**(ユーザーと合意済み):
1. ユーザーがAIS Japan(要ログイン。**アシスタント側からはアクセス不可、認証情報も受け取らない**)から
   該当ページをPDF/スクショで提供する
   - ENR 2.1 … 進入管制区・管制圏・情報圏の水平/垂直限界
   - ENR 5.5 … 民間訓練/試験空域
   - (必要に応じ ENR 5.1/5.2 … 制限空域等)
2. 度分秒座標(例: `354129N 1394650E`)をパースしてポリゴン化
3. 実装は新配列 `ASP_POLY` を追加する想定:

```js
// 提案スキーマ
{n:'東京進入管制区', t:'app'|'ctr'|'inf'|'trn'|'rst',
 upper:'FL150', lower:'SFC',
 pts:[[lat,lng],...],            // 多角形
 arcs:[{c:[lat,lng],r_nm:9,from:120,to:240}] } // 円弧境界がある場合
```

4. 描画: 種別ごとに色分け(進入管制区=緑系、訓練/試験=赤系破線を提案)、
   ツールチップに名称+上限/下限高度。凡例(`#legend`)にも追加
5. **未確定事項**: ユーザーの運航エリアがまだ聞けていない(全国かエリア限定か)。
   資料が来たらエリアを確認してから着手

**DMSパーサの仕様メモ**: AIPは `DDMMSS.S N / DDDMMSS.S E` 形式。
`along circle of radius ... centered on ...` のような円弧記述が混ざるので注意。

## 9. その他のバックログ(優先度順の提案)

1. **飛行場データの正式化** — AIP AD編から周波数(TWR/GND/ATIS)・運用時間・トラフィックパターン。
   現在ポップアップの周波数欄は「AIP AD参照」のプレースホルダ
2. **ルート編集強化** — 区間途中へのWP挿入、並べ替え(現在は末尾追加のみ)
3. **トラックログ** — GPS軌跡の記録・表示・GPX出力(飛行ログと連動)
4. **気象庁ナウキャスト対応** — RainViewerとの切替式
5. **他機情報の自動更新** — 現在は手動ボタン。10〜15秒ポーリング+自機からの距離警告
6. **複数ルート保存** — 現在は1ルートのみ自動保存。名前付き保存リスト化
7. **磁気偏差の自動推定** — 地図中心の緯度経度からWMM近似(現在は手入力)

## 10. UIデザイン規約

- 配色はCSS変数のみ使用: `--grn`(正常値/緑) `--amb`(燃料・注意/アンバー)
  `--mag`(フライトプラン/マゼンタ) `--cyn`(Direct-To・LIVE/シアン) `--red`(警告) `--blu`(管制圏・共有系)
- 数値・方位・時刻は必ず `--mono`(IBM Plex Mono)、方位は3桁+°、時間はh:mm
- GPS由来の値には「LIVE」タグ、デモデータには「DEMO」タグを必ず表示(実データとの混同防止)
- モバイル前提: タップ領域を小さくしない、テーブルは横スクロール許容

## 11. 既知の制限・注意

- 飛行ログのOFF/ONは手動ボタン(自動検出なし)。離陸ボタン押し忘れ対策は未実装
- ETE合計は各レグの風補正GSの積算。実GS連動時は現在GSを全レグに適用する簡易方式
- 空域円・飛行場データ(標高・滑走路含む)は**開発用サンプル**。正式データ反映まで
  「※サンプルデータ」表記を消さないこと
- localStorage依存のため、ブラウザのサイトデータ削除でログが消える(README記載済み、CSV書出で退避)
- 共有コードに位置情報(ルート)が含まれる。取り扱い注意の旨はユーザー了承済み

## 12. ユーザーコンテキスト

- 職業ヘリパイロット(日本)。航空用語はプロレベル、遠慮なく専門用語でよい
- 開発の進め方: 機能要望が来る→動くバージョンを丸ごと1ファイルで返す、の反復
- 風向の真/磁の区別、WCA、Direct-To等の概念説明は不要
- 安全に関わる注記(参考情報である旨)はユーザーも了承の上で維持している
