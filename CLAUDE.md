# HELI NAV 引き継ぎ資料(Claude Code向け)

最終更新: 2026-07-10 / 現行バージョン: v6.1(PWA・関東AIP空域ポリゴン実装済み)

進行中タスク・バックログは **BACKLOG.md** に分離した(このファイルは恒久情報のみ)。

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
heli-nav-pwa/            … 場所: ~/Claudeディレクトリ/heli-nav-pwa (git管理)
├─ index.html    … アプリ本体(HTML+CSS+JS全部入り)
├─ sw.js         … Service Worker(オフラインキャッシュ)
├─ manifest.json … PWAマニフェスト
├─ icon-192.png / icon-512.png
├─ README.md     … GitHub Pages公開・インストール手順(ユーザー向け)
├─ BACKLOG.md    … 進行中・未着手タスク(セッション開始時に指示があれば読む)
└─ tools/
   ├─ gen_asp.py       … AIP空域ポリゴン生成(要 shapely)。index.htmlの
   │                      /*ASP_POLY_GEN_START*/〜END区間へ --splice で埋め込む
   └─ asp_poly.gen.js  … 生成物のコピー(参照用)
```

デプロイ: GitHub Pages(main / root)。**index.html等を変更したら sw.js 先頭の
`const VER` を必ずインクリメント**(しないと既存端末に更新が届かない)。
**ローカルプレビューでも同じ**: Service Workerが古いindex.htmlをキャッシュして
配り続けるため、編集後の動作確認前に必ずVERを上げ、リロードを2回行うこと
(1回目でSW更新、2回目で新キャッシュから表示)。

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
| 空域 | 関東=AIP正式ポリゴン(CTR青/情報圏アンバー/PCA赤、ツールチップに上下限・周波数)。他地域=概略円のまま | `ASP[]` `ASP_POLY[]` `aspLayer` |
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

// 空域・飛行場マスタ ASP[](概略円+飛行場マーカー兼用)
{n:'東京(羽田)', icao:'RJTT', t:'ctr'|'inf'|'ap', lat, lng,
 r?:半径km(既定9), elev?:ft, rwy?:'文字列',
 poly?:1}  // poly=1: ASP_POLYに正式形状あり→概略円を描かない。t:'ap'=圏なし飛行場

// AIP正式空域 ASP_POLY[](tools/gen_asp.py が自動生成・手編集禁止)
{n:'東京PCA NR1', icao:'RJTT', t:'ctr'|'inf'|'pca',
 up:6000, lo:1500,   // 上限/下限 ft (lo=0はSFC)
 rmk:'連絡先周波数・運用時間等', pts:[[lat,lng],...]}

// localStorageキー
'hnav.route' / 'hnav.logs' / 'hnav.base'(ベース地図index)
```

## 8. AIP空域データの取り扱い(2026-07確立・重要)

**関東の空域ポリゴン化は完了**(AIRAC 2026-07-09基準)。以下は恒久ノウハウ。

### データソース(旧AIS Japanは廃止済み)
- **AIS Japanは2025年に廃止** → 現在は **SWIMポータル**(https://top.swim.mlit.go.jp/swim/、
  要ログイン)からAIP一式をダウンロードする。
  **アシスタントのブラウザ操作は.go.jpドメイン制限で不可**。ユーザーがDLして
  `~/Downloads/1_AIP (PDF)/<日付>/` に置く運用
- **管制圏・情報圏の水平/垂直限界は ENR 2.1 ではなく AD2(各飛行場)の AD 2.17** に載っている
  (当初想定のENR 2.1はFIR/ACCセクターのみ)。特別管制区(PCA)は
  RJTT/RJAAのAD2内チャート(座標表つき)。民間訓練試験空域は ENR 5.3.1
- **調布(RJTF)の情報圏は廃止済み**(AD 2.17=Nil)。東京ヘリポート(RJTI)はAD2自体なし
- PDF処理: `pdftotext -layout`(brew poppler)。チャート図の区分読解は
  `pdftoppm -png -r 300` で画像化 → 座標プロットとの重ね合わせで検証する手法が確立済み

### AIRAC更新手順(28日ごと・半自動)
1. ユーザーが新AIRACのAIP一式をSWIMからDL
2. 関東各飛行場のAD 2.17とPCAチャートの差分を確認
3. 変更があれば `tools/gen_asp.py` のSPECを修正 →
   `python3 tools/gen_asp.py --splice` で index.html を更新
4. `sw.js` の VER をインクリメントしてコミット

### 実装メモ
- 幾何計算はshapely(局所equirect平面、NM単位)。円=buffer、半平面クリップ、
  円同士の交点(立川/入間)、DMEアーク(成田PCAの9.4/5.4NM)対応済み
- 横田CTR=5nm円−立川CTR−入間CTR、木更津CTRは南側条件の入れ子(北帯1000/中帯1500/南2000)
- 東京PCA=中央円+NE扇形6帯+南アーム6帯+NEXUS+NR2(北西)4帯の計18区画。
  NR2は0600-1000UTCのみ。詳細は gen_asp.py のコメント参照

## 9. バックログ

**BACKLOG.md に分離した。** 着手時はセッション冒頭で「BACKLOG.mdの◯番」と指示を受ける。

## 10. UIデザイン規約

- 配色はCSS変数のみ使用: `--grn`(正常値/緑) `--amb`(燃料・注意/アンバー)
  `--mag`(フライトプラン/マゼンタ) `--cyn`(Direct-To・LIVE/シアン) `--red`(警告) `--blu`(管制圏・共有系)
- 数値・方位・時刻は必ず `--mono`(IBM Plex Mono)、方位は3桁+°、時間はh:mm
- GPS由来の値には「LIVE」タグ、デモデータには「DEMO」タグを必ず表示(実データとの混同防止)
- モバイル前提: タップ領域を小さくしない、テーブルは横スクロール許容

## 11. 既知の制限・注意

- 飛行ログのOFF/ONは手動ボタン(自動検出なし)。離陸ボタン押し忘れ対策は未実装
- ETE合計は各レグの風補正GSの積算。実GS連動時は現在GSを全レグに適用する簡易方式
- **関東の空域ポリゴンはAIP 2026-07-09現在の正式形状**(凡例に基準日を表示)。
  **関東以外の空域円は開発用サンプルのまま**(「※概略円」表記を消さないこと)。
  飛行場ポップアップの標高・滑走路は関東の一部を除きサンプル値
- localStorage依存のため、ブラウザのサイトデータ削除でログが消える(README記載済み、CSV書出で退避)
- 共有コードに位置情報(ルート)が含まれる。取り扱い注意の旨はユーザー了承済み

## 12. ユーザーコンテキスト

- 職業ヘリパイロット(日本)。航空用語はプロレベル、遠慮なく専門用語でよい
- 開発の進め方: 機能要望が来る→動くバージョンを丸ごと1ファイルで返す、の反復
- 風向の真/磁の区別、WCA、Direct-To等の概念説明は不要
- 安全に関わる注記(参考情報である旨)はユーザーも了承の上で維持している
